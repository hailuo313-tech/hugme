"""Telegram accounts API for P1-09 multi-account management."""

from datetime import datetime, timedelta
from typing import List
from uuid import uuid4
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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
from core.database import AsyncSessionLocal
from api.admin import require_operator
from services.telegram_account_manager import (
    _with_admin_display_name,
    telegram_account_manager,
)
from services.telegram_session_login import (
    TelegramSessionLoginError,
    TelegramSessionPasswordRequired,
    telegram_session_login_manager,
)

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
    admin_display_name: str | None = None
    username: str | None
    user_id: int | None
    is_connected: bool
    last_connected_at: str | None
    last_error_at: str | None
    error_message: str | None
    reply_mode: str = "ai"


class TelegramAccountStatusResponse(BaseModel):
    """Response with all accounts status."""

    accounts: List[TelegramAccountResponse]
    total: int
    connected_count: int


class TelegramAccountReplyModeRequest(BaseModel):
    """Request to switch an account between AI system and fixed replies."""

    reply_mode: str = Field(..., description="ai or fixed")


class TelegramAccountAdminDisplayNameRequest(BaseModel):
    """Request to update the operator-facing display label."""

    admin_display_name: str = Field(default="", description="Operator display name shown in reports")


class TelegramApiCredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=8, max_length=128)
    max_accounts: int | None = Field(default=None, gt=0)
    sort_order: int | None = None
    note: str | None = None


class SessionLoginStartRequest(BaseModel):
    """Request to send a Telegram login verification code."""

    phone: str = Field(..., description="Phone number in international format")
    display_name: str = Field(default="", description="Optional display name")
    api_credential_id: UUID | None = None


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


@router.get("/api/v1/telegram/api-credentials")
async def list_telegram_api_credentials(_operator=Depends(require_operator)):
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(text("""SELECT c.id::text,c.name,c.api_id,c.api_hash,c.is_default,c.is_active,
          c.max_accounts,c.sort_order,c.note,COUNT(a.id) account_count
          FROM telegram_api_credentials c LEFT JOIN telegram_accounts a
            ON a.api_credential_id=c.id AND a.is_active=TRUE AND a.status <> 'banned'
          GROUP BY c.id ORDER BY c.sort_order,c.name"""))).mappings().all()
    items=[]
    for serial,row in enumerate(rows,1):
        value=dict(row); secret=str(value.pop("api_hash") or "")
        value.update(serial_no=serial,serial_label=f"API-{serial:02d}",api_hash_masked=f"****{secret[-4:]}" if secret else "")
        items.append(value)
    return {"credentials":items,"total":len(items)}


@router.post("/api/v1/telegram/api-credentials",status_code=status.HTTP_201_CREATED)
async def create_telegram_api_credential(payload: TelegramApiCredentialCreateRequest, _operator=Depends(require_operator)):
    async with AsyncSessionLocal() as db:
        try:
            row=(await db.execute(text("""INSERT INTO telegram_api_credentials
              (name,api_id,api_hash,is_default,is_active,max_accounts,sort_order,note)
              VALUES(:name,:api_id,:api_hash,
                NOT EXISTS(SELECT 1 FROM telegram_api_credentials WHERE is_active AND is_default),
                TRUE,:max_accounts,COALESCE(:sort_order,0),:note) RETURNING id::text"""),
              {"name":payload.name.strip(),"api_id":payload.api_id,"api_hash":payload.api_hash.strip(),
               "max_accounts":payload.max_accounts,"sort_order":payload.sort_order,"note":payload.note})).scalar_one()
            await db.commit()
            return {"ok":True,"id":row}
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409,detail="开发者应用名称或API配置已存在") from exc
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
            metadata=_with_admin_display_name(request.metadata, request.display_name or None),
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
async def start_telegram_session_login_v2(
    request: SessionLoginStartRequest,
    _operator: dict = Depends(require_operator),
):
    """Send Telegram verification code via the shared session login manager."""
    try:
        result = await telegram_session_login_manager.start_login(
            phone=request.phone.strip(),
            display_name=request.display_name.strip() or None,
            api_credential_id=request.api_credential_id,
        )
    except TelegramSessionLoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SessionLoginStartResponse(
        login_id=result["login_id"],
        phone=result["phone"],
        expires_at=result["expires_at"],
        message="verification code sent",
    )


@router.post(
    "/api/v1/telegram/session-login/verify",
    response_model=SessionLoginVerifyResponse,
)
async def verify_telegram_session_login_v2(
    request: SessionLoginVerifyRequest,
    _operator: dict = Depends(require_operator),
):
    """Verify Telegram login via the shared session login manager."""
    try:
        result = await telegram_session_login_manager.verify_login(
            login_id=request.login_id,
            code=request.code.strip() if request.code else None,
            password=request.password,
            display_name=request.display_name.strip() or None,
            auto_connect=request.auto_connect,
        )
    except TelegramSessionPasswordRequired:
        return SessionLoginVerifyResponse(
            status="password_required",
            requires_password=True,
            message="2FA password required",
        )
    except TelegramSessionLoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SessionLoginVerifyResponse(
        account_id=result.get("account_id"),
        phone=result.get("phone"),
        status=result.get("status") or "disconnected",
        requires_password=bool(result.get("requires_password")),
        message="account saved",
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
        if not client.is_connected():
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
        operator_display_name = (
            request.display_name.strip()
            or (item.get("display_name") or "").strip()
        )
        display_name = (
            operator_display_name
            or getattr(me, "first_name", None)
            or phone
        )
        account_id = await telegram_account_manager.upsert_account(
            phone=phone,
            session_string=session_string,
            is_bot=False,
            display_name=display_name,
            metadata=_with_admin_display_name(
                {"login_method": "telethon_code"},
                operator_display_name or None,
            ),
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
    except IntegrityError as e:
        logger.error(f"Failed to delete Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="账号仍有关联任务，无法删除。请稍后重试或联系运维清理关联数据。",
        )
    except Exception as e:
        logger.error(f"Failed to delete Telegram account {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除账号失败，请稍后重试。",
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


@router.patch("/api/v1/telegram/accounts/{account_id}/admin-display-name", response_model=TelegramAccountResponse)
async def update_telegram_account_admin_display_name(
    account_id: str,
    request: TelegramAccountAdminDisplayNameRequest,
    _operator=Depends(require_operator),
):
    """Update the operator-facing display label used on /admin/data."""
    try:
        account_uuid = UUID(account_id)
        account_status = await telegram_account_manager.update_admin_display_name(
            account_uuid,
            request.admin_display_name,
        )
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
        logger.error(f"Failed to update Telegram account admin display name {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新显示名称失败，请稍后重试。",
        )


@router.patch("/api/v1/telegram/accounts/{account_id}/reply-mode", response_model=TelegramAccountResponse)
async def update_telegram_account_reply_mode(
    account_id: str,
    request: TelegramAccountReplyModeRequest,
    _operator=Depends(require_operator),
):
    """Switch one Telegram account between the normal AI pipeline and fixed replies."""
    if request.reply_mode not in {"ai", "fixed"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reply_mode must be ai or fixed",
        )
    try:
        account_uuid = UUID(account_id)
        account_status = await telegram_account_manager.update_reply_mode(
            account_uuid,
            request.reply_mode,
        )
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
        logger.error(f"Failed to update Telegram account reply mode {account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update account reply mode: {str(e)}",
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


@router.post("/api/v1/telegram/accounts/sync-profiles", response_model=dict)
async def sync_telegram_account_profiles():
    """Refresh connected Telegram account profiles from live sessions."""
    try:
        result = await telegram_account_manager.sync_connected_account_profiles()
        return {
            "message": "Telegram account profiles synced",
            **result,
        }
    except Exception as e:
        logger.error(f"Failed to sync Telegram account profiles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync account profiles: {str(e)}",
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
