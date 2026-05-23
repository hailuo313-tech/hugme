"""Telegram accounts API for P1-09 multi-account management."""

from datetime import datetime, timedelta
from typing import List
from uuid import uuid4
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from core.config import settings
from services.telegram_account_manager import telegram_account_manager

router = APIRouter()

_LOGIN_TTL = timedelta(minutes=10)
_pending_logins: dict[str, dict] = {}


class TelegramAccountCreateRequest(BaseModel):
    """Request to add a new Telegram account."""

    phone: str = Field(..., description="Phone number in international format (e.g., +1234567890)")
    session_string: str = Field(..., description="Telethon StringSession (will be encrypted)")
    is_bot: bool = Field(default=False, description="Whether this is a bot account")
    display_name: str = Field(default="", description="Display name for the account")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class TelegramAccountResponse(BaseModel):
    """Response with Telegram account status."""

    id: str
    phone: str
    status: str
    is_active: bool
    display_name: str | None
    username: str | None
    user_id: int | None
    is_connected: bool
    last_connected_at: str | None
    last_error_at: str | None
    error_message: str | None


class TelegramAccountStatusResponse(BaseModel):
    """Response with all accounts status."""

    accounts: List[TelegramAccountResponse]
    total: int
    connected_count: int


class SessionLoginStartRequest(BaseModel):
    """Request to send a Telegram login verification code."""

    phone: str = Field(..., description="Phone number in international format")
    display_name: str = Field(default="", description="Optional display name")


class SessionLoginStartResponse(BaseModel):
    """Response after a Telegram login code is sent."""

    login_id: str
    phone: str
    expires_at: str
    message: str


class SessionLoginVerifyRequest(BaseModel):
    """Request to verify Telegram login code and persist StringSession."""

    login_id: str
    code: str | None = None
    password: str | None = None
    display_name: str = ""
    auto_connect: bool = True


class SessionLoginVerifyResponse(BaseModel):
    """Response after Telegram login verification."""

    account_id: str | None = None
    phone: str | None = None
    status: str
    requires_password: bool = False
    message: str


def _require_telegram_login_config() -> None:
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TELEGRAM_API_ID / TELEGRAM_API_HASH 未配置",
        )
    if not settings.TELEGRAM_SESSION_FERNET_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TELEGRAM_SESSION_FERNET_KEY 未配置",
        )


async def _cleanup_expired_logins() -> None:
    now = datetime.utcnow()
    expired_ids = [
        login_id for login_id, item in _pending_logins.items()
        if item["expires_at"] <= now
    ]
    for login_id in expired_ids:
        item = _pending_logins.pop(login_id, None)
        client = item.get("client") if item else None
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


@router.post("/api/v1/telegram/accounts", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_telegram_account(request: TelegramAccountCreateRequest):
    """Add a new Telegram account.

    The session_string will be encrypted using TELEGRAM_SESSION_FERNET_KEY.
    """
    try:
        account_id = await telegram_account_manager.add_account(
            phone=request.phone,
            session_string=request.session_string,
            is_bot=request.is_bot,
            display_name=request.display_name or None,
            metadata=request.metadata,
        )

        logger.info(f"Added Telegram account {account_id} for phone {request.phone}")

        return {
            "id": str(account_id),
            "phone": request.phone,
            "status": "disconnected",
            "message": "Account added successfully. Use POST /connect to connect.",
        }
    except Exception as e:
        logger.error(f"Failed to add Telegram account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add account: {str(e)}",
        )


@router.post(
    "/api/v1/telegram/session-login/start",
    response_model=SessionLoginStartResponse,
)
async def start_telegram_session_login(request: SessionLoginStartRequest):
    """Send Telegram verification code and keep a short-lived login session."""
    _require_telegram_login_config()
    await _cleanup_expired_logins()

    phone = request.phone.strip()
    login_id = str(uuid4())
    expires_at = datetime.utcnow() + _LOGIN_TTL
    client = TelegramClient(
        StringSession(),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
        device_model=settings.TELEGRAM_DEVICE_MODEL,
        system_version=settings.TELEGRAM_SYSTEM_VERSION,
    )

    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        _pending_logins[login_id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "display_name": request.display_name.strip(),
            "expires_at": expires_at,
        }
        logger.info(f"Telegram login code sent for {phone}")
        return SessionLoginStartResponse(
            login_id=login_id,
            phone=phone,
            expires_at=expires_at.isoformat(),
            message="验证码已发送",
        )
    except PhoneNumberInvalidError:
        await client.disconnect()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="手机号格式无效，请使用国际区号格式，例如 +12025550123",
        )
    except HTTPException:
        await client.disconnect()
        raise
    except Exception as e:
        await client.disconnect()
        logger.error(f"Failed to send Telegram login code for {phone}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"发送验证码失败: {str(e)}",
        )


@router.post(
    "/api/v1/telegram/session-login/verify",
    response_model=SessionLoginVerifyResponse,
)
async def verify_telegram_session_login(request: SessionLoginVerifyRequest):
    """Verify Telegram login code, generate StringSession, encrypt and save it."""
    _require_telegram_login_config()
    await _cleanup_expired_logins()

    item = _pending_logins.get(request.login_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="登录流程已过期，请重新发送验证码",
        )

    client: TelegramClient = item["client"]
    phone: str = item["phone"]

    try:
        if not await client.is_connected():
            await client.connect()

        if request.password:
            await client.sign_in(password=request.password)
        else:
            if not request.code:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="请输入 Telegram 验证码",
                )
            await client.sign_in(
                phone=phone,
                code=request.code.strip(),
                phone_code_hash=item["phone_code_hash"],
            )

        me = await client.get_me()
        session_string = client.session.save()
        display_name = (
            request.display_name.strip()
            or item.get("display_name")
            or getattr(me, "first_name", None)
            or phone
        )
        account_id = await telegram_account_manager.upsert_account(
            phone=phone,
            session_string=session_string,
            is_bot=False,
            display_name=display_name,
            metadata={"login_method": "telethon_code"},
        )

        _pending_logins.pop(request.login_id, None)
        await client.disconnect()

        if request.auto_connect:
            await telegram_account_manager.connect_account(account_id)

        return SessionLoginVerifyResponse(
            account_id=str(account_id),
            phone=phone,
            status="connected" if request.auto_connect else "disconnected",
            requires_password=False,
            message="账号已添加",
        )
    except SessionPasswordNeededError:
        return SessionLoginVerifyResponse(
            status="password_required",
            requires_password=True,
            message="该账号开启了两步验证，请输入 2FA 密码",
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期，请重新发送验证码",
        )
    except PasswordHashInvalidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA 密码错误，请重新输入",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify Telegram login for {phone}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"验证登录失败: {str(e)}",
        )

@router.post("/api/v1/telegram/accounts/{account_id}/connect", response_model=dict)
async def connect_telegram_account(account_id: str):
    """Connect a Telegram account.

    This will establish a Telethon connection using the stored StringSession.
    """
    try:
        account_uuid = UUID(account_id)
        success = await telegram_account_manager.connect_account(account_uuid)

        if success:
            account_status = await telegram_account_manager.get_account_status(account_uuid)
            return {
                "account_id": account_id,
                "status": "connected",
                "account": account_status,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to connect account. Check error_message in account status.",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except Exception as e:
        logger.error(f"Failed to connect Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect account: {str(e)}",
        )


@router.post("/api/v1/telegram/accounts/{account_id}/disconnect", response_model=dict)
async def disconnect_telegram_account(account_id: str):
    """Disconnect a Telegram account."""
    try:
        account_uuid = UUID(account_id)
        success = await telegram_account_manager.disconnect_account(account_uuid)

        if success:
            return {
                "account_id": account_id,
                "status": "disconnected",
                "message": "Account disconnected successfully",
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to disconnect account",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except Exception as e:
        logger.error(f"Failed to disconnect Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect account: {str(e)}",
        )


@router.delete("/api/v1/telegram/accounts/{account_id}", response_model=dict)
async def delete_telegram_account(account_id: str):
    """Permanently delete a Telegram account."""
    try:
        account_uuid = UUID(account_id)
        success = await telegram_account_manager.delete_account(account_uuid)

        if success:
            return {
                "account_id": account_id,
                "status": "deleted",
                "message": "Account deleted successfully",
            }

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete account: {str(e)}",
        )


@router.get("/api/v1/telegram/accounts/{account_id}", response_model=TelegramAccountResponse)
async def get_telegram_account(account_id: str):
    """Get status of a specific Telegram account."""
    try:
        account_uuid = UUID(account_id)
        account_status = await telegram_account_manager.get_account_status(account_uuid)

        if not account_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        return TelegramAccountResponse(**account_status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account ID format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get account: {str(e)}",
        )


@router.get("/api/v1/telegram/accounts", response_model=TelegramAccountStatusResponse)
async def get_all_telegram_accounts():
    """Get status of all Telegram accounts."""
    try:
        accounts_status = await telegram_account_manager.get_all_accounts_status()
        connected_count = sum(1 for acc in accounts_status if acc["is_connected"])

        return TelegramAccountStatusResponse(
            accounts=[TelegramAccountResponse(**acc) for acc in accounts_status],
            total=len(accounts_status),
            connected_count=connected_count,
        )
    except Exception as e:
        logger.error(f"Failed to get Telegram accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get accounts: {str(e)}",
        )


@router.post("/api/v1/telegram/accounts/connect-all", response_model=dict)
async def connect_all_telegram_accounts():
    """Connect all active Telegram accounts."""
    try:
        results = await telegram_account_manager.connect_all_active_accounts()
        connected_count = sum(1 for success in results.values() if success)

        return {
            "total": len(results),
            "connected": connected_count,
            "failed": len(results) - connected_count,
            "results": {str(k): v for k, v in results.items()},
        }
    except Exception as e:
        logger.error(f"Failed to connect all Telegram accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect accounts: {str(e)}",
        )


@router.post("/api/v1/telegram/accounts/disconnect-all", response_model=dict)
async def disconnect_all_telegram_accounts():
    """Disconnect all Telegram accounts."""
    try:
        await telegram_account_manager.disconnect_all_accounts()
        return {
            "message": "All accounts disconnected successfully",
        }
    except Exception as e:
        logger.error(f"Failed to disconnect all Telegram accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect accounts: {str(e)}",
        )
