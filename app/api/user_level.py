"""User level API endpoints for P2-12 testing and management."""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from services.user_level_service import user_level_service

router = APIRouter()


class UserLevelRequest(BaseModel):
    """Request to calculate user level."""

    external_user_id: str = Field(..., description="External user ID (e.g., tg_123456789)")
    country_code: Optional[str] = Field(None, description="User's country code (ISO 3166-1 alpha-2)")


class UserLevelResponse(BaseModel):
    """Response with user level calculation result."""

    external_user_id: str
    telegram_user_id: Optional[str]
    level: str
    chat_route: str
    reason: str
    country_tier: str
    profile_complete: bool
    lifetime_spend_usd: float
    vip_level: int
    operator_assigned_s: bool


class ConfigReloadResponse(BaseModel):
    """Response for configuration reload."""

    success: bool
    message: str


@router.post(
    "/api/v1/user-level/calculate",
    response_model=UserLevelResponse,
    tags=["user-level"],
)
async def calculate_user_level(request: UserLevelRequest):
    """Calculate user level for testing and debugging."""
    try:
        result = await user_level_service.calculate_user_level_from_inbound(
            request.external_user_id,
            request.country_code,
        )

        return UserLevelResponse(**result)

    except Exception as e:
        logger.error(f"Error calculating user level: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate user level: {str(e)}",
        )


@router.post(
    "/api/v1/user-level/config/reload",
    response_model=ConfigReloadResponse,
    tags=["user-level"],
)
async def reload_level_config():
    """Reload level thresholds configuration (for P2-06 hot reload)."""
    try:
        await user_level_service.invalidate_thresholds_cache()
        logger.info("Level configuration reloaded via API")

        return ConfigReloadResponse(
            success=True,
            message="Level configuration reloaded successfully",
        )

    except Exception as e:
        logger.error(f"Error reloading level configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload configuration: {str(e)}",
        )