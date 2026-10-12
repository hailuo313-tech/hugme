"""Session manager for P1-18: Session encryption and auto-reconnect."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from uuid import UUID

from loguru import logger
from telethon import TelegramClient
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    SessionPasswordNeededError,
)
from telethon.network.connection import Connection
from telethon.sessions import StringSession

from core.config import settings
from core.database import get_async_session
from models.telegram_accounts import TelegramAccount
from services.mtproto.session_crypto import decrypt_string_session, encrypt_string_session
from services.telegram_account_manager import telegram_account_manager


class SessionManager:
    """Manage Telegram sessions with auto-reconnect and persistence."""

    def __init__(
        self,
        reconnect_interval: int = 30,
        max_reconnect_attempts: int = 5,
        health_check_interval: int = 60,
    ):
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.health_check_interval = health_check_interval

        self.reconnect_tasks: Dict[UUID, asyncio.Task] = {}
        self.health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False
        self._connection_failures: Dict[UUID, int] = {}
        self._health_cursor = 0

    async def start(self):
        """Start session manager background tasks."""
        if self._running:
            logger.warning("Session manager already running")
            return

        self._running = True
        logger.info("Starting session manager")

        # Finish restoring all accounts before health checks begin. Otherwise
        # not-yet-restored clients are falsely marked missing and reconnected.
        await self._restore_sessions()
        if self._running:
            self.health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        """Stop session manager background tasks."""
        if not self._running:
            return

        logger.info("Stopping session manager")
        self._running = False

        # Cancel health check task
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        # Cancel all reconnect tasks
        for task in self.reconnect_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.reconnect_tasks.clear()

    async def _restore_sessions(self):
        """Restore active sessions from database on startup."""
        logger.info("Restoring sessions from database")
        accounts = await telegram_account_manager.get_active_accounts()
        if not accounts:
            return
        for account in accounts:
            if account.status == "banned":
                logger.warning(f"Skipping banned Telegram account {account.id}")
                continue
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account.id)):
                logger.info(f"Skipping restore for account {account.id}; owned by another runtime")
                continue

            logger.info(f"Restoring session for account {account.id} status={account.status}")
            from services.telegram_command_gateway import submit_telegram_command

            async def _legacy_restore(account_id=account.id):
                return await telegram_account_manager.connect_account(account_id)

            gated = await submit_telegram_command(
                command_type="connect_account",
                account_id=str(account.id),
                legacy_execute=_legacy_restore,
            )
            if gated.accepted_not_sent:
                logger.info(f"Session restore for account {account.id} queued for runtime")
                continue
            if not gated.executed:
                logger.warning(
                    f"Failed to restore session for account {account.id}: {gated.reason}"
                )
                self._schedule_reconnect(account.id)
                continue
            success = bool(gated.value)
            if success:
                logger.info(f"Successfully restored session for account {account.id}")
            else:
                logger.warning(f"Failed to restore session for account {account.id}, will retry")
                self._schedule_reconnect(account.id)

    async def _health_check_loop(self):
        """Periodically check connection health of all sessions."""
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_all_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _check_all_connections(self):
        """Check health of all connected accounts."""
        accounts = await telegram_account_manager.get_active_accounts()
        if not accounts:
            return
        # Probe a bounded rotating slice. Full scans every minute overload both
        # Telegram and PostgreSQL and synchronize reconnects across all accounts.
        batch_size = min(20, len(accounts))
        start = self._health_cursor % len(accounts)
        ordered = accounts[start:] + accounts[:start]
        accounts = ordered[:batch_size]
        self._health_cursor = (start + batch_size) % len(ordered)

        for account in accounts:
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account.id)):
                continue
            if account.status == "connected":
                client = telegram_account_manager.clients.get(account.id)
                reason = ""
                if client and client.is_connected():
                    try:
                        await client.get_me()
                        self._connection_failures.pop(account.id, None)
                        continue
                    except Exception as exc:
                        reason = str(exc)
                else:
                    reason = "Client not available"

                failures = self._connection_failures.get(account.id, 0) + 1
                self._connection_failures[account.id] = failures
                logger.bind(account_id=str(account.id), consecutive_failures=failures).warning(
                    "mtproto.session_health.transient_failure"
                )
                if failures < 3:
                    continue

                self._connection_failures.pop(account.id, None)
                await telegram_account_manager.disconnect_account(account.id)
                await self._handle_disconnect(account.id, reason)

    async def _handle_disconnect(self, account_id: UUID, reason: str):
        """Handle unexpected disconnection."""
        from services.runtime_ownership import this_process_may_hold_telegram_session

        if not await this_process_may_hold_telegram_session(str(account_id)):
            logger.info(f"Skip disconnect handling for account {account_id}; owned by another runtime")
            return
        logger.warning(f"Handling disconnect for account {account_id}: {reason}")

        # Update status in database
        await telegram_account_manager._update_account_status(account_id, "disconnected", reason)

        # Schedule reconnect if account is still active
        account = await telegram_account_manager.get_account(account_id)
        if account and account.is_active:
            self._schedule_reconnect(account_id)

    def _schedule_reconnect(self, account_id: UUID):
        """Schedule a reconnection attempt for an account."""
        if account_id in self.reconnect_tasks:
            return  # Already scheduled

        async def _guarded_schedule():
            from services.runtime_ownership import this_process_may_hold_telegram_session

            if not await this_process_may_hold_telegram_session(str(account_id)):
                logger.info(f"Skip reconnect schedule for account {account_id}; owned by another runtime")
                return
            await self._reconnect_with_backoff(account_id)

        logger.info(f"Scheduling reconnect for account {account_id} in {self.reconnect_interval}s")
        task = asyncio.create_task(_guarded_schedule())
        self.reconnect_tasks[account_id] = task

    async def _reconnect_with_backoff(self, account_id: UUID, attempt: int = 1):
        """Reconnect with exponential backoff."""
        if not self._running:
            return

        if attempt > self.max_reconnect_attempts:
            logger.error(f"Max reconnect attempts reached for account {account_id}")
            await telegram_account_manager._update_account_status(
                account_id, "error", f"Max reconnect attempts ({self.max_reconnect_attempts}) reached"
            )
            self.reconnect_tasks.pop(account_id, None)
            return

        # Calculate backoff delay (exponential)
        delay = min(self.reconnect_interval * (2 ** (attempt - 1)), 300)  # Max 5 minutes

        logger.info(f"Reconnect attempt {attempt}/{self.max_reconnect_attempts} for account {account_id} in {delay}s")

        await asyncio.sleep(delay)

        if not self._running:
            return

        try:
            from services.telegram_command_gateway import submit_telegram_command

            async def _legacy_reconnect():
                return await telegram_account_manager.connect_account(account_id)

            gated = await submit_telegram_command(
                command_type="connect_account",
                account_id=str(account_id),
                legacy_execute=_legacy_reconnect,
            )
            if gated.accepted_not_sent:
                logger.info(f"Reconnect for account {account_id} queued for runtime")
                self.reconnect_tasks.pop(account_id, None)
                return
            if not gated.executed:
                raise RuntimeError(gated.reason or "telegram_gateway_rejected")
            success = bool(gated.value)
            if success:
                logger.info(f"Successfully reconnected account {account_id}")
                self.reconnect_tasks.pop(account_id, None)
            else:
                # Retry with backoff
                await self._reconnect_with_backoff(account_id, attempt + 1)
        except AuthKeyUnregisteredError:
            logger.error(f"Account {account_id} auth key unregistered (banned)")
            await telegram_account_manager._update_account_status(account_id, "banned", "Auth key unregistered")
            self.reconnect_tasks.pop(account_id, None)
        except AuthKeyDuplicatedError:
            logger.error(f"Account {account_id} auth key duplicated")
            await telegram_account_manager._update_account_status(account_id, "error", "Auth key duplicated")
            self.reconnect_tasks.pop(account_id, None)
        except Exception as e:
            logger.error(f"Reconnect failed for account {account_id}: {e}")
            await self._reconnect_with_backoff(account_id, attempt + 1)

    async def save_session(
        self,
        account_id: UUID,
        session_string: str,
        encrypt: bool = True,
    ) -> bool:
        """Save or update session string for an account."""
        try:
            encrypted_session = encrypt_string_session(session_string, settings.TELEGRAM_SESSION_FERNET_KEY) if encrypt else session_string

            async for session in get_async_session():
                account = await session.get(TelegramAccount, account_id)
                if account:
                    account.session_string = encrypted_session
                    account.updated_at = datetime.utcnow()
                    session.add(account)
                    await session.commit()
                    logger.info(f"Saved session for account {account_id}")
                    return True
                else:
                    logger.error(f"Account {account_id} not found")
                    return False
        except Exception as e:
            logger.error(f"Failed to save session for account {account_id}: {e}")
            return False

    async def load_session(self, account_id: UUID) -> Optional[str]:
        """Load and decrypt session string for an account."""
        try:
            account = await telegram_account_manager.get_account(account_id)
            if not account:
                logger.error(f"Account {account_id} not found")
                return None

            decrypted_session = decrypt_string_session(
                account.session_string.encode(),
                settings.TELEGRAM_SESSION_FERNET_KEY,
            )
            return decrypted_session
        except Exception as e:
            logger.error(f"Failed to load session for account {account_id}: {e}")
            return None

    async def delete_session(self, account_id: UUID) -> bool:
        """Delete session for an account (disconnect and clear)."""
        try:
            # Disconnect if connected
            await telegram_account_manager.disconnect_account(account_id)

            # Cancel any pending reconnect
            if account_id in self.reconnect_tasks:
                self.reconnect_tasks[account_id].cancel()
                self.reconnect_tasks.pop(account_id, None)

            # Clear session string in database
            async for session in get_async_session():
                account = await session.get(TelegramAccount, account_id)
                if account:
                    account.session_string = ""
                    account.status = "disconnected"
                    account.updated_at = datetime.utcnow()
                    session.add(account)
                    await session.commit()
                    logger.info(f"Deleted session for account {account_id}")
                    return True
                else:
                    logger.error(f"Account {account_id} not found")
                    return False
        except Exception as e:
            logger.error(f"Failed to delete session for account {account_id}: {e}")
            return False

    async def get_session_status(self, account_id: UUID) -> Optional[dict]:
        """Get session status including reconnect info."""
        account = await telegram_account_manager.get_account(account_id)
        if not account:
            return None

        is_reconnecting = account_id in self.reconnect_tasks

        return {
            "account_id": str(account_id),
            "status": account.status,
            "is_connected": account.status == "connected",
            "is_reconnecting": is_reconnecting,
            "last_connected_at": account.last_connected_at.isoformat() if account.last_connected_at else None,
            "last_error_at": account.last_error_at.isoformat() if account.last_error_at else None,
            "error_message": account.error_message,
        }

    async def get_all_sessions_status(self) -> list:
        """Get status of all sessions."""
        accounts = await telegram_account_manager.get_active_accounts()
        statuses = []

        for account in accounts:
            status = await self.get_session_status(account.id)
            if status:
                statuses.append(status)

        return statuses


# Global instance
session_manager = SessionManager(
    reconnect_interval=getattr(settings, "SESSION_RECONNECT_INTERVAL", 30),
    max_reconnect_attempts=getattr(settings, "SESSION_MAX_RECONNECT_ATTEMPTS", 5),
    health_check_interval=getattr(settings, "SESSION_HEALTH_CHECK_INTERVAL", 60),
)
