"""Two-step Telethon login that produces encrypted StringSession accounts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from core.config import settings
from services.telegram_account_manager import telegram_account_manager


class TelegramSessionLoginError(Exception):
    """Safe user-facing error for the session login flow."""


class TelegramSessionPasswordRequired(Exception):
    """Raised when Telegram requires a 2FA password after code verification."""


@dataclass
class PendingTelegramLogin:
    login_id: str
    phone: str
    phone_code_hash: str
    client: TelegramClient
    display_name: str | None
    created_at: datetime
    expires_at: datetime
    requires_password: bool = False


class TelegramSessionLoginManager:
    """Manage short-lived Telethon login clients until StringSession is saved."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.pending: dict[str, PendingTelegramLogin] = {}
        self._lock = asyncio.Lock()

    async def start_login(self, phone: str, display_name: str | None = None) -> dict[str, str]:
        """Send a Telegram login code and keep the client in memory briefly."""
        self._ensure_configured()
        await self._cleanup_expired()

        client = TelegramClient(
            StringSession(),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            device_model=settings.TELEGRAM_DEVICE_MODEL,
            system_version=settings.TELEGRAM_SYSTEM_VERSION,
        )

        try:
            await client.connect()
            sent_code = await client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            await _disconnect_quietly(client)
            raise TelegramSessionLoginError("手机号格式无效或 Telegram 不接受该号码") from exc
        except FloodWaitError as exc:
            await _disconnect_quietly(client)
            raise TelegramSessionLoginError(f"Telegram 限流，请等待 {exc.seconds} 秒后再试") from exc
        except Exception as exc:
            await _disconnect_quietly(client)
            logger.warning("telegram_session_login.start_failed phone={}", _mask_phone(phone))
            raise TelegramSessionLoginError("发送验证码失败，请检查 API 配置和手机号") from exc

        now = datetime.now(UTC)
        login_id = str(uuid4())
        async with self._lock:
            self.pending[login_id] = PendingTelegramLogin(
                login_id=login_id,
                phone=phone,
                phone_code_hash=sent_code.phone_code_hash,
                client=client,
                display_name=display_name or None,
                created_at=now,
                expires_at=now + self.ttl,
            )

        logger.info("telegram_session_login.code_sent login_id={} phone={}", login_id, _mask_phone(phone))
        return {
            "login_id": login_id,
            "phone": phone,
            "expires_at": self.pending[login_id].expires_at.isoformat(),
        }

    async def verify_login(
        self,
        login_id: str,
        code: str | None = None,
        password: str | None = None,
        display_name: str | None = None,
        auto_connect: bool = False,
    ) -> dict[str, Any]:
        """Verify code or 2FA password, save StringSession as a Telegram account."""
        await self._cleanup_expired()
        pending = self.pending.get(login_id)
        if pending is None:
            raise TelegramSessionLoginError("登录流程已过期，请重新发送验证码")

        try:
            if pending.requires_password:
                if not password:
                    raise TelegramSessionPasswordRequired()
                await pending.client.sign_in(password=password)
            else:
                if not code:
                    raise TelegramSessionLoginError("请输入 Telegram 验证码")
                await pending.client.sign_in(
                    phone=pending.phone,
                    code=code,
                    phone_code_hash=pending.phone_code_hash,
                )
        except SessionPasswordNeededError as exc:
            pending.requires_password = True
            raise TelegramSessionPasswordRequired() from exc
        except PasswordHashInvalidError as exc:
            raise TelegramSessionLoginError("2FA 密码不正确") from exc
        except PhoneCodeInvalidError as exc:
            raise TelegramSessionLoginError("验证码不正确") from exc
        except PhoneCodeExpiredError as exc:
            await self._discard(login_id)
            raise TelegramSessionLoginError("验证码已过期，请重新发送") from exc
        except Exception as exc:
            logger.warning("telegram_session_login.verify_failed login_id={}", login_id)
            raise TelegramSessionLoginError("验证码登录失败，请稍后重试") from exc

        if not await pending.client.is_user_authorized():
            raise TelegramSessionLoginError("Telegram 未完成授权，请重新登录")

        me = await pending.client.get_me()
        session_string = pending.client.session.save()
        chosen_display_name = display_name or pending.display_name or getattr(me, "first_name", None) or ""

        account_id = await telegram_account_manager.add_account(
            phone=pending.phone,
            session_string=session_string,
            is_bot=False,
            display_name=chosen_display_name or None,
            metadata={
                "session_source": "admin_telethon_login",
                "telegram_user_id": getattr(me, "id", None),
                "telegram_username": getattr(me, "username", None),
            },
        )

        await self._discard(login_id)

        connected = False
        if auto_connect:
            connected = await telegram_account_manager.connect_account(account_id)

        logger.info(
            "telegram_session_login.saved account_id={} phone={} auto_connect={}",
            account_id,
            _mask_phone(pending.phone),
            auto_connect,
        )
        return {
            "account_id": str(account_id),
            "phone": pending.phone,
            "status": "connected" if connected else "disconnected",
            "requires_password": False,
            "telegram_user_id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
            "display_name": chosen_display_name or None,
        }

    async def _cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [login_id for login_id, pending in self.pending.items() if pending.expires_at <= now]
        for login_id in expired:
            await self._discard(login_id)

    async def _discard(self, login_id: str) -> None:
        async with self._lock:
            pending = self.pending.pop(login_id, None)
        if pending:
            await _disconnect_quietly(pending.client)

    def _ensure_configured(self) -> None:
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            raise TelegramSessionLoginError("TELEGRAM_API_ID / TELEGRAM_API_HASH 未配置")
        if not settings.TELEGRAM_SESSION_FERNET_KEY:
            raise TelegramSessionLoginError("TELEGRAM_SESSION_FERNET_KEY 未配置")


async def _disconnect_quietly(client: TelegramClient) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass


def _mask_phone(phone: str) -> str:
    if len(phone) <= 5:
        return "***"
    return f"{phone[:3]}***{phone[-2:]}"


telegram_session_login_manager = TelegramSessionLoginManager()
