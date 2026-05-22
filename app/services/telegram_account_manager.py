"""Telegram account manager for P1-09 multi-account StringSession management."""

import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID
from uuid import uuid4

from cryptography.fernet import Fernet
from loguru import logger
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon import events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core.config import settings
from core.database import AsyncSessionLocal, get_async_session
from models.telegram_accounts import TelegramAccount
from services.telegram_real_user_auto_reply import handle_mtproto_inbound_auto_reply


class TelegramAccountManager:
    """Manage multiple Telegram accounts with StringSession."""

    def __init__(self):
        self.clients: Dict[UUID, TelegramClient] = {}
        self._inbound_handlers: Dict[UUID, object] = {}
        self.fernet = Fernet(settings.TELEGRAM_SESSION_FERNET_KEY.encode()) if settings.TELEGRAM_SESSION_FERNET_KEY else None
        self._encrypted_session_cache: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._redis = None

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
        async with _session_scope() as session:
            result = await session.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            return await _maybe_await(result.scalar_one_or_none())

    async def get_active_accounts(self) -> List[TelegramAccount]:
        """Get all active accounts from database."""
        async with _session_scope() as session:
            result = await session.execute(
                select(TelegramAccount).where(TelegramAccount.is_active == True)
            )
            scalars = await _maybe_await(result.scalars())
            accounts = await _maybe_await(scalars.all())
            return list(accounts)

    async def connect_account(self, account_id: UUID) -> bool:
        """Connect a Telegram account."""
        async with self._lock:
            account = await self.get_account(account_id)
            if not account:
                logger.error(f"Account {account_id} not found")
                return False

            if account_id in self.clients:
                logger.info(f"Account {account_id} already connected")
                return True

            try:
                await self._update_account_status(account_id, "connecting")

                session_string = self._decrypt_session(account.session_string)

                # Create Telegram client
                client = TelegramClient(
                    _build_string_session(session_string),
                    settings.TELEGRAM_API_ID,
                    settings.TELEGRAM_API_HASH,
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

                await self._mark_account_connected(account_id, me)

                # Store client
                self.clients[account_id] = client
                await self._register_inbound_handler(account_id, client)

                return True

            except SessionPasswordNeededError as e:
                logger.error(f"Account {account_id} requires 2FA password: {e}")
                await self._update_account_status(account_id, "error", "2FA password required")
                return False
            except Exception as e:
                logger.error(f"Failed to connect account {account_id}: {e}")
                await self._update_account_status(account_id, "error", str(e))
                return False

    async def disconnect_account(self, account_id: UUID) -> bool:
        """Disconnect a Telegram account."""
        async with self._lock:
            client = self.clients.pop(account_id, None)
            handler = self._inbound_handlers.pop(account_id, None)
            if client:
                try:
                    if handler is not None:
                        client.remove_event_handler(handler)
                    await client.disconnect()
                    logger.info(f"Disconnected account {account_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting account {account_id}: {e}")

            await self._update_account_status(account_id, "disconnected")
            return True

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

    async def _register_inbound_handler(self, account_id: UUID, client: TelegramClient) -> None:
        if account_id in self._inbound_handlers:
            return

        redis = await self._get_redis()
        account_id_text = str(account_id)

        async def _handler(raw_event):
            try:
                await handle_mtproto_inbound_auto_reply(
                    client=client,
                    raw_event=raw_event,
                    redis=redis,
                    account_id=account_id_text,
                )
            except Exception as exc:
                logger.bind(account_id=account_id_text, error_type=type(exc).__name__).error(
                    f"mtproto_auto_reply.handler_error: {exc}"
                )

        client.add_event_handler(_handler, events.NewMessage(incoming=True))
        self._inbound_handlers[account_id] = _handler
        logger.bind(account_id=account_id_text).info("telegram_account.inbound_handler_registered")

    async def _get_redis(self):
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        return self._redis

    async def add_account(
        self,
        phone: str,
        session_string: str,
        is_bot: bool = False,
        display_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> UUID:
        """Add a new Telegram account."""
        encrypted_session = self._encrypt_session(session_string)

        async with _session_scope() as session:
            account = TelegramAccount(
                id=uuid4(),
                phone=phone,
                session_string=encrypted_session,
                is_bot=is_bot,
                display_name=display_name,
                metadata_json=metadata or {},
            )
            session.add(account)
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
        async with _session_scope() as session:
            account = await session.get(TelegramAccount, account_id)
            if account:
                account.status = status
                account.error_message = error_message
                if status == "error":
                    account.last_error_at = datetime.utcnow()
                session.add(account)
                await session.commit()

    async def _mark_account_connected(self, account_id: UUID, me) -> None:
        """Persist connected account metadata using the current database session."""
        async with _session_scope() as session:
            account = await session.get(TelegramAccount, account_id)
            if account:
                account.status = "connected"
                account.display_name = getattr(me, "first_name", None) or ""
                account.username = getattr(me, "username", None)
                account.user_id = getattr(me, "id", None)
                account.last_connected_at = datetime.utcnow()
                account.error_message = None
                session.add(account)
                await session.commit()

    async def get_account_status(self, account_id: UUID) -> Optional[dict]:
        """Get account status."""
        account = await self.get_account(account_id)
        if not account:
            return None

        is_connected = account_id in self.clients
        return _account_status_payload(account, is_connected)

    async def get_all_accounts_status(self) -> List[dict]:
        """Get all accounts status."""
        accounts = await self.get_active_accounts()
        return [
            _account_status_payload(account, account.id in self.clients)
            for account in accounts
        ]


# Global instance
telegram_account_manager = TelegramAccountManager()


@asynccontextmanager
async def _session_scope():
    if getattr(get_async_session, "__module__", None) == "core.database":
        async with AsyncSessionLocal() as session:
            yield session
        return

    session = await _next_session()
    yield session


async def _next_session() -> AsyncSession:
    source = get_async_session
    if hasattr(source, "__anext__"):
        return await source.__anext__()
    session_iter = source()
    if hasattr(session_iter, "__anext__"):
        return await session_iter.__anext__()
    async for session in session_iter:
        return session
    raise RuntimeError("get_async_session produced no session")


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _build_string_session(session_string: str) -> StringSession:
    try:
        return StringSession(session_string)
    except ValueError:
        logger.warning("Invalid Telegram StringSession, using empty session shell")
        return StringSession()


def _account_status_payload(account: TelegramAccount, is_connected: bool) -> dict:
    return {
        "id": str(account.id),
        "phone": account.phone,
        "status": account.status,
        "is_active": account.is_active,
        "display_name": account.display_name,
        "username": account.username,
        "user_id": account.user_id,
        "is_connected": is_connected,
        "last_connected_at": account.last_connected_at.isoformat() if account.last_connected_at else None,
        "last_error_at": account.last_error_at.isoformat() if account.last_error_at else None,
        "error_message": account.error_message,
    }
