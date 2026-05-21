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

    async def start(self):
        """Start session manager background tasks."""
        if self._running:
            logger.warning("Session manager already running")
            return

        self._running = True
        logger.info("Starting session manager")

        # Start health check task
        self.health_check_task = asyncio.create_task(self._health_check_loop())

        # Restore sessions from database
        await self._restore_sessions()

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

        for account in accounts:
            if account.status == "connected":
                logger.info(f"Restoring session for account {account.id}")
                success = await telegram_account_manager.connect_account(account.id)
                if success:
                    logger.info(f"Successfully restored session for account {account.id}")
                else:
                    logger.warning(f"Failed to restore session for account {account.id}, will retry")
                    # Schedule reconnect
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

        for account in accounts:
            if account.status == "connected":
                client = await telegram_account_manager.get_client(account.id)
                if client and client.is_connected():
                    try:
                        # Send a simple request to verify connection
                        await client.get_me()
                    except Exception as e:
                        logger.warning(f"Account {account.id} connection unhealthy: {e}")
                        await self._handle_disconnect(account.id, str(e))
                else:
                    logger.warning(f"Account {account.id} is marked connected but client not available")
                    await self._handle_disconnect(account.id, "Client not available")

    async def _handle_disconnect(self, account_id: UUID, reason: str):
        """Handle unexpected disconnection."""
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

        logger.info(f"Scheduling reconnect for account {account_id} in {self.reconnect_interval}s")
        task = asyncio.create_task(self._reconnect_with_backoff(account_id))
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
            success = await telegram_account_manager.connect_account(account_id)
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