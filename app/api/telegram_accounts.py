"""Telegram accounts API for P1-09 multi-account management."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from api.admin import require_operator
from services.telegram_session_login import (
    TelegramSessionLoginError,
    TelegramSessionPasswordRequired,
    telegram_session_login_manager,
)
from services.telegram_account_manager import telegram_account_manager

router = APIRouter()


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


class TelegramSessionLoginStartRequest(BaseModel):
    """Start a Telethon phone-code login flow."""

    phone: str = Field(..., description="Phone number in international format")
    display_name: str = Field(default="", description="Optional display name")


class TelegramSessionLoginStartResponse(BaseModel):
    """Response after sending Telegram code."""

    login_id: str
    phone: str
    expires_at: str


class TelegramSessionLoginVerifyRequest(BaseModel):
    """Verify a Telegram code or 2FA password and save StringSession."""

    login_id: str = Field(..., description="Login flow ID from /session-login/start")
    code: str | None = Field(default=None, description="Telegram login code")
    password: str | None = Field(default=None, description="2FA password when required")
    display_name: str = Field(default="", description="Optional display name override")
    auto_connect: bool = Field(default=False, description="Connect account after saving session")


class TelegramSessionLoginVerifyResponse(BaseModel):
    """Response after verifying Telegram login."""

    account_id: str | None = None
    phone: str | None = None
    status: str
    requires_password: bool = False
    telegram_user_id: int | None = None
    username: str | None = None
    display_name: str | None = None


@router.post(
    "/api/v1/telegram/session-login/start",
    response_model=TelegramSessionLoginStartResponse,
)
async def start_telegram_session_login(
    request: TelegramSessionLoginStartRequest,
    _operator: dict = Depends(require_operator),
):
    """Send Telegram login code for creating a Telethon StringSession."""
    try:
        result = await telegram_session_login_manager.start_login(
            phone=request.phone,
            display_name=request.display_name or None,
        )
        return TelegramSessionLoginStartResponse(**result)
    except TelegramSessionLoginError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/api/v1/telegram/session-login/verify",
    response_model=TelegramSessionLoginVerifyResponse,
)
async def verify_telegram_session_login(
    request: TelegramSessionLoginVerifyRequest,
    _operator: dict = Depends(require_operator),
):
    """Verify Telegram code/2FA and save encrypted StringSession."""
    try:
        result = await telegram_session_login_manager.verify_login(
            login_id=request.login_id,
            code=request.code,
            password=request.password,
            display_name=request.display_name or None,
            auto_connect=request.auto_connect,
        )
        return TelegramSessionLoginVerifyResponse(**result)
    except TelegramSessionPasswordRequired:
        return TelegramSessionLoginVerifyResponse(
            status="password_required",
            requires_password=True,
        )
    except TelegramSessionLoginError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


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
    """Delete a Telegram account after disconnecting any active client."""
    try:
        account_uuid = UUID(account_id)
        success = await telegram_account_manager.delete_account(account_uuid)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        return {
            "account_id": account_id,
            "status": "deleted",
            "message": "Account deleted successfully",
        }
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
            detail="删除 Telegram 账号失败，请稍后重试或联系管理员。",
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
