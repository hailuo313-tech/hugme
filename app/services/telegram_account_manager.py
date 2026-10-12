"""Telegram account manager for P1-09 multi-account StringSession management."""

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core.config import settings
from core.database import AsyncSessionLocal
from models.telegram_accounts import TelegramAccount
from services.runtime_shadow_state import (
    read_shadow_account_status,
    schedule_shadow_account_status,
    shadow_payload_is_live_connected,
)

try:
    from services.runtime_shadow_state import read_all_shadow_account_statuses
except ImportError:  # older runtime image lacks the bulk reader
    async def read_all_shadow_account_statuses(*_args, **_kwargs):
        return {}

ADMIN_DISPLAY_NAME_KEY = "admin_display_name"


def _schedule_incoming_video_listener(account_id: UUID) -> None:
    try:
        from services.call_broadcast.incoming_listener import schedule_register_incoming_listener

        schedule_register_incoming_listener(account_id)
    except Exception:
        return


def _merge_metadata(existing: dict | None, updates: dict | None) -> dict:
    merged = dict(existing or {})
    if updates:
        merged.update(updates)
    return merged


def _with_admin_display_name(metadata: dict | None, operator_display_name: str | None) -> dict:
    merged = dict(metadata or {})
    cleaned = (operator_display_name or "").strip()
    if cleaned:
        merged[ADMIN_DISPLAY_NAME_KEY] = cleaned
    return merged


def _looks_like_operator_display_name(display_name: str | None, username: str | None = None) -> bool:
    cleaned = (display_name or "").strip()
    if not cleaned:
        return False
    if len(cleaned) > 32:
        return False
    lowered = cleaned.lower()
    if any(token in lowered for token in ("add me", "tiktok", "cam2", "cam ")):
        return False
    if any(ch in cleaned for ch in "💋👅🍑🥺💦🔥"):
        return False
    if username and cleaned.lower() == username.lower():
        return False
    return True


def _preserve_admin_display_name(account: TelegramAccount, upcoming_profile_name: str | None = None) -> None:
    metadata = dict(account.metadata_json or {})
    if (metadata.get(ADMIN_DISPLAY_NAME_KEY) or "").strip():
        account.metadata_json = metadata
        return
    current = (account.display_name or "").strip()
    upcoming = (upcoming_profile_name or "").strip()
    if current and current != upcoming:
        metadata[ADMIN_DISPLAY_NAME_KEY] = current
        account.metadata_json = metadata


def _operator_display_name_from_metadata(metadata: dict | None) -> str | None:
    stored = ((metadata or {}).get(ADMIN_DISPLAY_NAME_KEY) or "").strip()
    return stored or None


def _apply_profile_from_metadata(account: TelegramAccount, metadata: dict | None) -> None:
    data = metadata or {}
    username = str(data.get("telegram_username") or "").strip() or None
    if username:
        account.username = username[:50]
    raw_user_id = data.get("telegram_user_id")
    if raw_user_id not in (None, ""):
        try:
            account.user_id = int(raw_user_id)
        except (TypeError, ValueError):
            pass


class TelegramAccountManager:
    """Manage multiple Telegram accounts with StringSession."""

    def __init__(self):
        self.clients: Dict[UUID, TelegramClient] = {}
        self._inbound_handlers: Dict[UUID, object] = {}
        self._inbox_watchdogs: Dict[UUID, asyncio.Task] = {}
        self._watchdog_seen_message_ids: dict[UUID, set[int]] = defaultdict(set)
        self.fernet = Fernet(settings.TELEGRAM_SESSION_FERNET_KEY.encode()) if settings.TELEGRAM_SESSION_FERNET_KEY else None
        self._encrypted_session_cache: Dict[str, str] = {}
        self._account_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _decrypt_session(self, encrypted_session: str) -> str:
        """Decrypt encrypted StringSession."""
        if not self.fernet:
            raise ValueError("TELEGRAM_SESSION_FERNET_KEY not configured")
        try:
            if encrypted_session in self._encrypted_session_cache:
                return self._encrypted_session_cache[encrypted_session]
            return self.fernet.decrypt(encrypted_session.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt session: {e}")
            raise

    def _encrypt_session(self, session_string: str) -> str:
        """Encrypt StringSession."""
        if not self.fernet:
            raise ValueError("TELEGRAM_SESSION_FERNET_KEY not configured")
        try:
            encrypted = self.fernet.encrypt(session_string.encode()).decode()
            self._encrypted_session_cache[encrypted] = session_string
            return encrypted
        except Exception as e:
            logger.error(f"Failed to encrypt session: {e}")
            raise

    async def get_account(self, account_id: UUID) -> Optional[TelegramAccount]:
        """Get account by ID from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            return result.scalar_one_or_none()

    async def get_active_accounts(self) -> List[TelegramAccount]:
        """Get all active accounts from database, newest first."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TelegramAccount)
                .where(TelegramAccount.is_active == True)
                .order_by(TelegramAccount.updated_at.desc(), TelegramAccount.created_at.desc())
            )
            return list(result.scalars().all())

    async def connect_account(self, account_id: UUID) -> bool:
        """Connect a Telegram account."""
        from services.runtime_ownership import this_process_may_hold_telegram_session

        if not await this_process_may_hold_telegram_session(str(account_id)):
            logger.info(f"Skip connect; this process must not hold account {account_id}")
            return False
        async with self._account_locks[str(account_id)]:
            account = await self.get_account(account_id)
            if not account:
                logger.error(f"Account {account_id} not found")
                return False
            if not account.is_active or (account.metadata_json or {}).get("duplicate_of"):
                logger.warning(f"Skip inactive or duplicate Telegram account {account_id}")
                return False

            existing_client = self.clients.get(account_id)
            if existing_client is not None:
                if existing_client.is_connected():
                    logger.info(f"Account {account_id} already connected")
                    self._schedule_private_inbox_watchdog(account_id, existing_client)
                    _schedule_incoming_video_listener(account_id)
                    return True

                # A cached Telethon object is not proof of a live MTProto
                # connection.  Reconnect the existing client before reporting
                # success; otherwise the session manager can loop forever while
                # health checks see ``Cannot send requests while disconnected``.
                logger.warning(f"Account {account_id} client cached but disconnected; reconnecting")
                try:
                    await existing_client.disconnect()
                    await existing_client.connect()
                    if not await existing_client.is_user_authorized():
                        self._remove_inbound_handler(account_id, existing_client)
                        self.clients.pop(account_id, None)
                        await existing_client.disconnect()
                        await self._update_account_status(
                            account_id, "error", "Session not authorized"
                        )
                        return False
                    await existing_client.get_me()
                    if account_id not in self._inbound_handlers:
                        self._register_inbound_handler(account_id, existing_client)
                    await self._update_account_status(account_id, "connected")
                    logger.info(f"Reconnected cached Telegram account {account_id}")
                    _schedule_incoming_video_listener(account_id)
                    return True
                except Exception as reconnect_error:
                    logger.warning(
                        f"Cached client reconnect failed for account {account_id}: {reconnect_error}"
                    )
                    self._remove_inbound_handler(account_id, existing_client)
                    self.clients.pop(account_id, None)
                    try:
                        await existing_client.disconnect()
                    except Exception:
                        pass

            try:
                # Update status to connecting without reusing the ORM object
                # across AsyncSession instances.
                await self._update_account_status(account_id, "connecting")

                # Decrypt session string
                session_string = self._decrypt_session(account.session_string)

                api_id, api_hash = await self._get_account_api_credentials(account)

                # Create Telegram client with the same developer application
                # that was used to create this StringSession.
                client = TelegramClient(
                    _build_string_session(session_string),
                    api_id,
                    api_hash,
                    device_model=settings.TELEGRAM_DEVICE_MODEL,
                    system_version=settings.TELEGRAM_SYSTEM_VERSION,
                )

                # Connect
                await client.connect()

                # Verify connection
                if not await client.is_user_authorized():
                    logger.error(f"Account {account_id} session is not authorized")
                    await client.disconnect()
                    await self._update_account_status(account_id, "error", "Session not authorized")
                    return False

                # Get account info
                me = await client.get_me()
                logger.info(f"Connected to Telegram account: {me.first_name} (@{me.username or 'no username'})")

                # Update account info on a fresh ORM instance bound to this
                # session. Reusing the object from get_account() can attach it
                # to two sessions and break reconnect/delete flows.
                async with AsyncSessionLocal() as session:
                    connected_account = await session.get(TelegramAccount, account_id)
                    if connected_account:
                        profile_name = me.first_name or ""
                        _preserve_admin_display_name(connected_account, profile_name)
                        connected_account.status = "connected"
                        connected_account.display_name = profile_name
                        connected_account.username = me.username
                        connected_account.user_id = me.id
                        connected_account.last_connected_at = datetime.utcnow()
                        connected_account.error_message = None
                        await session.commit()
                schedule_shadow_account_status(str(account_id), "connected")

                # Store client
                self._register_inbound_handler(account_id, client)
                self.clients[account_id] = client
                self._schedule_private_inbox_watchdog(account_id, client)
                _schedule_incoming_video_listener(account_id)

                return True

            except SessionPasswordNeededError as e:
                logger.error(f"Account {account_id} requires 2FA password: {e}")
                await self._update_account_status(account_id, "error", "2FA password required")
                return False
            except Exception as e:
                logger.error(f"Failed to connect account {account_id}: {e}")
                await self._update_account_status(account_id, "error", str(e))
                return False

    async def _get_account_api_credentials(self, account: TelegramAccount) -> tuple[int, str]:
        if not account.api_credential_id:
            return int(settings.TELEGRAM_API_ID), str(settings.TELEGRAM_API_HASH)
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                text("""SELECT api_id, api_hash FROM telegram_api_credentials
                        WHERE id = :credential_id AND is_active = TRUE"""),
                {"credential_id": account.api_credential_id},
            )).mappings().one_or_none()
        if not row:
            raise ValueError("Telegram developer application is missing or inactive")
        return int(row["api_id"]), str(row["api_hash"])

    async def disconnect_account(self, account_id: UUID) -> bool:
        """Disconnect a Telegram account."""
        async with self._account_locks[str(account_id)]:
            client = self.clients.pop(account_id, None)
            self._cancel_private_inbox_watchdog(account_id)
            if client:
                try:
                    self._remove_inbound_handler(account_id, client)
                    await client.disconnect()
                    logger.info(f"Disconnected account {account_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting account {account_id}: {e}")

            await self._update_account_status(account_id, "disconnected")
            return True

    async def _purge_account_dependencies(self, session, account_id: UUID) -> None:
        """Remove rows that block telegram_accounts delete."""
        account_id_str = str(account_id)
        params = {"account_id": account_id}
        await session.execute(
            text("DELETE FROM telegram_user_migration_tasks WHERE source_account_id = :account_id OR target_account_id = :account_id"),
            params,
        )
        await session.execute(
            text("DELETE FROM telegram_user_migration_campaigns WHERE source_account_id = :account_id OR target_account_id = :account_id"),
            params,
        )
        await session.execute(
            text("DELETE FROM call_broadcast_jobs WHERE account_id = :account_id"),
            params,
        )
        await session.execute(
            text("DELETE FROM fixed_auto_reply_jobs WHERE account_id = :account_id"),
            params,
        )
        # message_schedules.account_id is varchar, not uuid.
        await session.execute(
            text("DELETE FROM message_schedules WHERE account_id = :account_id"),
            {"account_id": account_id_str},
        )

    async def delete_account(self, account_id: UUID) -> bool:
        """Disconnect and permanently delete a Telegram account."""
        async with self._account_locks[str(account_id)]:
            client = self.clients.pop(account_id, None)
            self._cancel_private_inbox_watchdog(account_id)
            if client:
                try:
                    self._remove_inbound_handler(account_id, client)
                    await client.disconnect()
                    logger.info(f"Disconnected account {account_id} before delete")
                except Exception as e:
                    logger.error(f"Error disconnecting account {account_id} before delete: {e}")

            async with AsyncSessionLocal() as session:
                account = await session.get(TelegramAccount, account_id)
                if not account:
                    logger.warning(f"Telegram account {account_id} not found for delete")
                    return False

                await self._purge_account_dependencies(session, account_id)
                await session.delete(account)
                await session.commit()
            logger.info(f"Deleted Telegram account {account_id}")
            return True

    def _register_inbound_handler(self, account_id: UUID, client: TelegramClient) -> None:
        """Register runtime MTProto NewMessage auto-reply handler."""
        if account_id in self._inbound_handlers:
            return
        try:
            from telethon import events
            from services.mtproto.auto_reply import handle_mtproto_new_message

            async def _handler(event):
                message = getattr(event, "message", event)
                message_id = int(getattr(message, "id", 0) or getattr(event, "id", 0) or 0)
                if message_id and not self._claim_inbound_message(account_id, message_id):
                    return
                try:
                    await handle_mtproto_new_message(client, account_id, event)
                except Exception:
                    if message_id:
                        self._watchdog_seen_message_ids[account_id].discard(message_id)
                    raise

            client.add_event_handler(_handler, events.NewMessage(incoming=True))
            self._inbound_handlers[account_id] = _handler
            logger.info(f"Registered Telegram inbound handler for account {account_id}")
        except Exception as e:
            logger.error(f"Failed to register Telegram inbound handler for {account_id}: {e}")
            raise

    def _claim_inbound_message(self, account_id: UUID, message_id: int) -> bool:
        """Prevent the live handler and watchdog from processing one update twice."""
        seen = self._watchdog_seen_message_ids[account_id]
        if message_id in seen:
            return False
        seen.add(message_id)
        if len(seen) > 1000:
            # Message ids increase within a Telegram account. Retaining the newest
            # half keeps memory bounded without reopening immediately recent ids.
            newest = sorted(seen, reverse=True)[:500]
            seen.clear()
            seen.update(newest)
        return True

    def _schedule_private_inbox_watchdog(self, account_id: UUID, client: TelegramClient) -> None:
        """Recover recent unread private messages when Telegram drops NewMessage updates."""
        current = self._inbox_watchdogs.get(account_id)
        if current is not None and not current.done():
            return
        self._inbox_watchdogs[account_id] = asyncio.create_task(
            self._run_private_inbox_watchdog(account_id, client)
        )

    def _cancel_private_inbox_watchdog(self, account_id: UUID) -> None:
        task = self._inbox_watchdogs.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _run_private_inbox_watchdog(self, account_id: UUID, client: TelegramClient) -> None:
        # Spread 358 account polls across the minute to avoid Telegram bursts.
        initial_delay = (account_id.int % 600) + 60
        await asyncio.sleep(initial_delay)
        first_pass = True
        while self.clients.get(account_id) is client and client.is_connected():
            try:
                # The first pass also recovers messages missed while the runtime
                # was disconnected. Later passes stay smaller to limit TG load.
                dialogs = await client.get_dialogs(limit=30 if first_pass else 20)
                cutoff = datetime.now(timezone.utc) - (
                    timedelta(hours=24) if first_pass else timedelta(minutes=30)
                )
                recovered_count = 0
                recovery_limit = 3
                for dialog in dialogs:
                    if recovered_count >= recovery_limit:
                        break
                    if not bool(getattr(dialog, "is_user", False)):
                        continue
                    unread = int(getattr(dialog, "unread_count", 0) or 0)
                    if unread <= 0 and not first_pass:
                        continue
                    history = list(
                        await client.get_messages(
                            getattr(dialog, "entity", None),
                            limit=10 if first_pass else min(unread, 10),
                        )
                    )
                    if first_pass:
                        # Opening a chat on the phone marks an unanswered message
                        # read. Recover only the newest consecutive inbound tail;
                        # an outbound message at the head proves it was answered.
                        pending: list = []
                        for history_message in history:
                            if getattr(history_message, "out", False):
                                break
                            pending.append(history_message)
                        messages_to_recover = reversed(pending)
                    else:
                        messages_to_recover = reversed(history)
                    for message in messages_to_recover:
                        if recovered_count >= recovery_limit:
                            break
                        message_date = getattr(message, "date", None)
                        if getattr(message, "out", False) or not message_date or message_date < cutoff:
                            continue
                        message_id = int(getattr(message, "id", 0) or 0)
                        if not message_id or not self._claim_inbound_message(account_id, message_id):
                            continue
                        from services.mtproto.auto_reply import handle_mtproto_new_message

                        class _RecoveredPrivateEvent:
                            is_private = True

                            def __init__(self, recovered_message, recovered_chat):
                                self.message = recovered_message
                                self.id = getattr(recovered_message, "id", None)
                                self.sender_id = getattr(recovered_message, "sender_id", None)
                                # The reply path accepts a Telethon entity. StringSession
                                # clients do not persist an integer-id entity cache.
                                self.chat_id = recovered_chat

                            async def get_sender(self):
                                return await self.message.get_sender()

                        logger.bind(
                            account_id=str(account_id),
                            telegram_message_id=str(getattr(message, "id", "")),
                        ).warning("mtproto.inbound.recovered_by_watchdog")
                        try:
                            await handle_mtproto_new_message(
                                client,
                                account_id,
                                _RecoveredPrivateEvent(message, getattr(dialog, "entity", None)),
                            )
                            recovered_count += 1
                        except Exception:
                            self._watchdog_seen_message_ids[account_id].discard(message_id)
                            raise
                first_pass = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.bind(
                    account_id=str(account_id),
                    error_type=type(exc).__name__,
                    reason=str(exc)[:300],
                ).warning("mtproto.inbox_watchdog.failed")
            await asyncio.sleep(600)

    def _remove_inbound_handler(self, account_id: UUID, client: TelegramClient) -> None:
        """Remove runtime MTProto NewMessage handler if it was registered."""
        handler = self._inbound_handlers.pop(account_id, None)
        if handler is None:
            return
        try:
            client.remove_event_handler(handler)
        except Exception as e:
            logger.warning(f"Failed to remove Telegram inbound handler for {account_id}: {e}")

    async def connect_all_active_accounts(self) -> Dict[UUID, bool]:
        """Connect all active accounts."""
        accounts = await self.get_active_accounts()
        results = {}

        for account in accounts:
            results[account.id] = await self.connect_account(account.id)

        return results

    async def disconnect_all_accounts(self) -> None:
        """Disconnect all accounts."""
        account_ids = list(self.clients.keys())
        for account_id in account_ids:
            await self.disconnect_account(account_id)

    async def get_client(self, account_id: UUID) -> Optional[TelegramClient]:
        """Get TelegramClient for an account."""
        return self.clients.get(account_id)

    async def get_any_connected_client(self) -> Optional[TelegramClient]:
        """Get any connected client for sending messages."""
        if not self.clients:
            return None
        return next(iter(self.clients.values()))

    async def add_account(
        self,
        phone: str,
        session_string: str,
        is_bot: bool = False,
        display_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> UUID:
        """Add a new Telegram account."""
        from sqlalchemy import text
        phone = "+" + "".join(char for char in phone if char in "0123456789")
        if phone == "+":
            raise ValueError("A valid Telegram phone number is required")
        encrypted_session = self._encrypt_session(session_string)

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:phone, 0))"), {"phone": phone})
            existing = (await session.execute(text("SELECT id FROM telegram_accounts WHERE regexp_replace(phone, '[^0-9]', '', 'g') = :phone LIMIT 1"), {"phone": phone[1:]})).first()
            if existing:
                raise ValueError("Telegram account already exists; update the existing account")
            merged_metadata = _with_admin_display_name(
                _merge_metadata(metadata, {}),
                _operator_display_name_from_metadata(metadata) or display_name,
            )
            account = TelegramAccount(
                phone=phone,
                session_string=encrypted_session,
                is_bot=is_bot,
                display_name=display_name,
                metadata_json=merged_metadata,
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account.id

    async def upsert_account(
        self,
        phone: str,
        session_string: str,
        is_bot: bool = False,
        display_name: Optional[str] = None,
        metadata: Optional[dict] = None,
        api_credential_id: Optional[UUID] = None,
    ) -> UUID:
        """Create or update an account by phone with a fresh StringSession."""
        from sqlalchemy import func, text
        phone = "+" + "".join(char for char in phone if char in "0123456789")
        if phone == "+":
            raise ValueError("A valid Telegram phone number is required")
        encrypted_session = self._encrypt_session(session_string)

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:phone, 0))"), {"phone": phone})
            result = await session.execute(
                select(TelegramAccount)
                .where(func.regexp_replace(TelegramAccount.phone, '[^0-9]', '', 'g') == phone[1:])
                .order_by(TelegramAccount.is_active.desc(), TelegramAccount.created_at.asc())
                .limit(1)
            )
            account = result.scalar_one_or_none()
            if account:
                account.session_string = encrypted_session
                account.is_bot = is_bot
                account.is_active = True
                account.api_credential_id = api_credential_id or account.api_credential_id
                account.display_name = display_name or account.display_name
                account.metadata_json = _with_admin_display_name(
                    _merge_metadata(account.metadata_json, metadata),
                    _operator_display_name_from_metadata(metadata)
                    or _operator_display_name_from_metadata(account.metadata_json)
                    or display_name,
                )
                _apply_profile_from_metadata(account, account.metadata_json)
                account.status = "disconnected"
                account.error_message = None
                account.updated_at = datetime.utcnow()
                await session.commit()
                return account.id

            account = TelegramAccount(
                phone=phone,
                session_string=encrypted_session,
                is_bot=is_bot,
                display_name=display_name,
                api_credential_id=api_credential_id,
                metadata_json=_with_admin_display_name(
                    _merge_metadata(metadata, {}),
                    _operator_display_name_from_metadata(metadata) or display_name,
                ),
            )
            _apply_profile_from_metadata(account, account.metadata_json)
            session.add(account)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(TelegramAccount).where(TelegramAccount.phone == phone)
                )
                account = result.scalar_one()
                account.session_string = encrypted_session
                account.is_active = True
                account.api_credential_id = api_credential_id or account.api_credential_id
                account.display_name = display_name or account.display_name
                account.metadata_json = _with_admin_display_name(
                    _merge_metadata(account.metadata_json, metadata),
                    _operator_display_name_from_metadata(metadata)
                    or _operator_display_name_from_metadata(account.metadata_json)
                    or display_name,
                )
                _apply_profile_from_metadata(account, account.metadata_json)
                account.status = "disconnected"
                account.error_message = None
                account.updated_at = datetime.utcnow()
                await session.commit()
            await session.refresh(account)
            return account.id

    async def _update_account_status(
        self,
        account_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Update account status in database."""
        async with AsyncSessionLocal() as session:
            account = await session.get(TelegramAccount, account_id)
            if account:
                account.status = status
                account.error_message = error_message
                if status == "error":
                    account.last_error_at = datetime.utcnow()
                await session.commit()
                schedule_shadow_account_status(str(account_id), status)

    async def get_account_status(self, account_id: UUID) -> Optional[dict]:
        """Get account status."""
        account = await self.get_account(account_id)
        if not account:
            return None

        is_connected = account_id in self.clients
        if not is_connected:
            is_connected = shadow_payload_is_live_connected(
                await read_shadow_account_status(str(account_id))
            )
        return _account_status_payload(account, is_connected)

    async def get_all_accounts_status(self) -> List[dict]:
        """Get all accounts status."""
        accounts = await self.get_active_accounts()
        shadow = {}
        if not self.clients or len(self.clients) < len(accounts):
            shadow = await read_all_shadow_account_statuses()
        now = time.time()
        cred_names: dict[str, str] = {}
        if any(account.api_credential_id for account in accounts):
            async with AsyncSessionLocal() as session:
                cred_rows = (await session.execute(
                    text("SELECT id::text AS id, name FROM telegram_api_credentials")
                )).mappings().all()
                cred_names = {str(row["id"]): str(row["name"] or "") for row in cred_rows}
        rows = []
        for account in accounts:
            connected = account.id in self.clients or shadow_payload_is_live_connected(
                shadow.get(str(account.id)),
                now=now,
            )
            payload = _account_status_payload(account, connected)
            if account.api_credential_id:
                payload["api_credential_id"] = str(account.api_credential_id)
                payload["api_credential_name"] = cred_names.get(str(account.api_credential_id))
            rows.append(payload)
        return rows

    async def sync_connected_account_profiles(self) -> dict:
        """Refresh DB profile fields from currently connected Telegram clients."""
        accounts = await self.get_active_accounts()
        result: dict = {
            "total": len(accounts),
            "synced": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

        for account in accounts:
            client = self.clients.get(account.id)
            if not client:
                connected = await self.connect_account(account.id)
                client = self.clients.get(account.id) if connected else None
                if not client:
                    result["skipped"] += 1
                    result["details"].append({
                        "account_id": str(account.id),
                        "phone": account.phone,
                        "status": "skipped",
                        "reason": "client_not_loaded",
                    })
                    continue

            try:
                if not client.is_connected():
                    connected = await self.connect_account(account.id)
                    client = self.clients.get(account.id) if connected else None
                    if not client:
                        raise RuntimeError("client_reconnect_failed")

                if not await client.is_user_authorized():
                    await self._update_account_status(account.id, "error", "Session not authorized")
                    result["failed"] += 1
                    result["details"].append({
                        "account_id": str(account.id),
                        "phone": account.phone,
                        "status": "failed",
                        "reason": "session_not_authorized",
                    })
                    continue

                me = await client.get_me()
                display_name = " ".join(
                    part for part in [
                        getattr(me, "first_name", None),
                        getattr(me, "last_name", None),
                    ]
                    if part
                ).strip()

                async with AsyncSessionLocal() as session:
                    db_account = await session.get(TelegramAccount, account.id)
                    if db_account:
                        profile_name = display_name or db_account.display_name or ""
                        _preserve_admin_display_name(db_account, profile_name)
                        db_account.status = "connected"
                        db_account.display_name = profile_name or db_account.display_name or ""
                        db_account.username = getattr(me, "username", None)
                        db_account.user_id = getattr(me, "id", None)
                        db_account.last_connected_at = datetime.utcnow()
                        db_account.error_message = None
                        db_account.updated_at = datetime.utcnow()
                        await session.commit()
                        schedule_shadow_account_status(str(account.id), "connected")

                result["synced"] += 1
                result["details"].append({
                    "account_id": str(account.id),
                    "phone": account.phone,
                    "status": "synced",
                    "display_name": display_name,
                    "username": getattr(me, "username", None),
                    "user_id": getattr(me, "id", None),
                })
            except Exception as e:
                logger.error(f"Failed to sync Telegram account profile {account.id}: {e}")
                await self._update_account_status(account.id, "error", str(e))
                result["failed"] += 1
                result["details"].append({
                    "account_id": str(account.id),
                    "phone": account.phone,
                    "status": "failed",
                    "reason": str(e),
                })

        return result

    async def update_reply_mode(self, account_id: UUID, reply_mode: str) -> Optional[dict]:
        """Update account-level reply mode without changing the Telegram session."""
        normalized = _normalize_reply_mode(reply_mode)
        async with AsyncSessionLocal() as session:
            account = await session.get(TelegramAccount, account_id)
            if not account:
                return None
            metadata = dict(account.metadata_json or {})
            metadata["reply_mode"] = normalized
            account.metadata_json = metadata
            account.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(account)
            return _account_status_payload(account, account.id in self.clients)

    async def update_admin_display_name(
        self,
        account_id: UUID,
        admin_display_name: str | None,
    ) -> Optional[dict]:
        """Update the operator-facing display label for one Telegram account."""
        cleaned = (admin_display_name or "").strip()
        async with AsyncSessionLocal() as session:
            account = await session.get(TelegramAccount, account_id)
            if not account:
                return None
            metadata = dict(account.metadata_json or {})
            if cleaned:
                metadata[ADMIN_DISPLAY_NAME_KEY] = cleaned
            else:
                metadata.pop(ADMIN_DISPLAY_NAME_KEY, None)
            account.metadata_json = metadata
            account.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(account)
            return _account_status_payload(account, account.id in self.clients)

    async def update_app_download_platform(
        self,
        account_id: UUID,
        platform_key: str,
    ) -> Optional[dict]:
        """Bind one Telegram account to an A-F download platform, or follow default."""
        from services.app_download_platforms import normalize_app_download_platform

        normalized = normalize_app_download_platform(platform_key)
        async with AsyncSessionLocal() as session:
            account = await session.get(TelegramAccount, account_id)
            if not account:
                return None
            metadata = dict(account.metadata_json or {})
            if normalized == "default":
                metadata.pop("app_download_platform", None)
            else:
                metadata["app_download_platform"] = normalized
            account.metadata_json = metadata
            account.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(account)
            return _account_status_payload(account, account.id in self.clients)


# Global instance
telegram_account_manager = TelegramAccountManager()


def _build_string_session(session_string: str) -> StringSession:
    try:
        return StringSession(session_string)
    except ValueError:
        logger.warning("Invalid Telegram StringSession, using empty session shell")
        return StringSession()


def _normalize_reply_mode(reply_mode: str | None) -> str:
    return "fixed" if reply_mode == "fixed" else "ai"


def _normalize_app_download_platform(value: str | None) -> str:
    from services.app_download_platforms import normalize_app_download_platform

    return normalize_app_download_platform(value)


def admin_display_name_from_account(account: TelegramAccount) -> str | None:
    metadata = account.metadata_json or {}
    stored = (metadata.get(ADMIN_DISPLAY_NAME_KEY) or "").strip()
    if stored:
        return stored
    legacy = (account.display_name or "").strip()
    if _looks_like_operator_display_name(legacy, account.username):
        return legacy
    return None


def _account_status_payload(account: TelegramAccount, is_connected: bool) -> dict:
    metadata = account.metadata_json or {}
    return {
        "id": str(account.id),
        "phone": account.phone,
        "status": account.status,
        "is_active": account.is_active,
        "display_name": account.display_name,
        "admin_display_name": admin_display_name_from_account(account),
        "username": account.username,
        "user_id": account.user_id,
        "is_connected": is_connected,
        "is_bot": bool(account.is_bot),
        "api_credential_id": str(account.api_credential_id) if account.api_credential_id else None,
        "api_credential_name": None,
        "last_connected_at": account.last_connected_at.isoformat() if account.last_connected_at else None,
        "last_error_at": account.last_error_at.isoformat() if account.last_error_at else None,
        "error_message": account.error_message,
        "reply_mode": _normalize_reply_mode(metadata.get("reply_mode")),
        "app_download_platform": _normalize_app_download_platform(metadata.get("app_download_platform")),
    }
