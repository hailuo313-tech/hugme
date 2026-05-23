"""Telegram account manager for P1-09 multi-account StringSession management."""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core.config import settings
from core.database import AsyncSessionLocal
from models.telegram_accounts import TelegramAccount


class TelegramAccountManager:
    """Manage multiple Telegram accounts with StringSession."""

    def __init__(self):
        self.clients: Dict[UUID, TelegramClient] = {}
        self._inbound_handlers: Dict[UUID, object] = {}
        self.fernet = Fernet(settings.TELEGRAM_SESSION_FERNET_KEY.encode()) if settings.TELEGRAM_SESSION_FERNET_KEY else None
        self._encrypted_session_cache: Dict[str, str] = {}
        self._lock = asyncio.Lock()

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
        """Get all active accounts from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TelegramAccount).where(TelegramAccount.is_active == True)
            )
            return list(result.scalars().all())

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
                # Update status to connecting without reusing the ORM object
                # across AsyncSession instances.
                await self._update_account_status(account_id, "connecting")

                # Decrypt session string
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

                # Update account info on a fresh ORM instance bound to this
                # session. Reusing the object from get_account() can attach it
                # to two sessions and break reconnect/delete flows.
                async with AsyncSessionLocal() as session:
                    connected_account = await session.get(TelegramAccount, account_id)
                    if connected_account:
                        connected_account.status = "connected"
                        connected_account.display_name = me.first_name or ""
                        connected_account.username = me.username
                        connected_account.user_id = me.id
                        connected_account.last_connected_at = datetime.utcnow()
                        connected_account.error_message = None
                        await session.commit()

                # Store client
                self._register_inbound_handler(account_id, client)
                self.clients[account_id] = client

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
            if client:
                try:
                    self._remove_inbound_handler(account_id, client)
                    await client.disconnect()
                    logger.info(f"Disconnected account {account_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting account {account_id}: {e}")

            await self._update_account_status(account_id, "disconnected")
            return True

    async def delete_account(self, account_id: UUID) -> bool:
        """Disconnect and permanently delete a Telegram account."""
        async with self._lock:
            client = self.clients.pop(account_id, None)
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
                await handle_mtproto_new_message(client, account_id, event)

            client.add_event_handler(_handler, events.NewMessage(incoming=True))
            self._inbound_handlers[account_id] = _handler
            logger.info(f"Registered Telegram inbound handler for account {account_id}")
        except Exception as e:
            logger.error(f"Failed to register Telegram inbound handler for {account_id}: {e}")
            raise

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
        encrypted_session = self._encrypt_session(session_string)

        async with AsyncSessionLocal() as session:
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

    async def upsert_account(
        self,
        phone: str,
        session_string: str,
        is_bot: bool = False,
        display_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> UUID:
        """Create or update an account by phone with a fresh StringSession."""
        encrypted_session = self._encrypt_session(session_string)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TelegramAccount).where(TelegramAccount.phone == phone)
            )
            account = result.scalar_one_or_none()
            if account:
                account.session_string = encrypted_session
                account.is_bot = is_bot
                account.is_active = True
                account.display_name = display_name or account.display_name
                account.metadata_json = metadata or account.metadata_json or {}
                account.status = "disconnected"
                account.error_message = None
                account.updated_at = datetime.utcnow()
                await session.commit()
                return account.id

            account = TelegramAccount(
                id=uuid4(),
                phone=phone,
                session_string=encrypted_session,
                is_bot=is_bot,
                display_name=display_name,
                metadata_json=metadata or {},
            )
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
                account.display_name = display_name or account.display_name
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
