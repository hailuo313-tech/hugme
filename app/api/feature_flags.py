"""
P5-09: Feature Flag Management API

REST API endpoints for managing feature flags with gradual rollout support.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from app.services.feature_flags import (
    FeatureFlagService, 
    RolloutType,
    feature_flag_service
)


# Pydantic models for request/response
class FeatureFlagCreate(BaseModel):
    """Model for creating a feature flag"""
    name: str = Field(..., description="Feature flag name (unique)", min_length=1, max_length=100)
    description: str = Field(..., description="Feature description")
    rollout_type: RolloutType = Field(default=RolloutType.ALL, description="Rollout strategy")
    rollout_percentage: int = Field(default=0, ge=0, le=100, description="Percentage for rollout (0-100)")
    target_levels: Optional[str] = Field(None, description="Comma-separated target levels (S,A,B,C,D)")
    target_user_ids: Optional[str] = Field(None, description="Comma-separated target user IDs")
    created_by: str = Field(default="api", description="Creator identifier")


class FeatureFlagUpdate(BaseModel):
    """Model for updating a feature flag"""
    enabled: Optional[bool] = Field(None, description="Enable/disable the flag")
    rollout_type: Optional[RolloutType] = Field(None, description="Rollout strategy")
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100, description="Percentage for rollout (0-100)")
    target_levels: Optional[str] = Field(None, description="Comma-separated target levels (S,A,B,C,D)")
    target_user_ids: Optional[str] = Field(None, description="Comma-separated target user IDs")
    updated_by: str = Field(default="api", description="Updater identifier")


class FeatureFlagCheck(BaseModel):
    """Model for checking feature flag status"""
    name: str = Field(..., description="Feature flag name")
    user_id: Optional[str] = Field(None, description="User ID for user-specific checks")
    user_level: Optional[str] = Field(None, description="User level (S/A/B/C/D)")


class FeatureFlagResponse(BaseModel):
    """Model for feature flag response"""
    id: int
    name: str
    description: str
    enabled: bool
    rollout_type: str
    rollout_percentage: int
    target_levels: Optional[str]
    target_user_ids: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: Optional[str]


class FeatureFlagCheckResponse(BaseModel):
    """Model for feature flag check response"""
    name: str
    enabled: bool
    rollout_type: str
    user_matches: bool
    reason: str


# Create router
router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


@router.post("/", response_model=FeatureFlagResponse)
async def create_feature_flag(
    flag_data: FeatureFlagCreate,
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Create a new feature flag
    
    - **name**: Unique feature flag name
    - **description**: Feature description
    - **rollout_type**: Rollout strategy (all/percentage/level/user_list)
    - **rollout_percentage**: Percentage for percentage-based rollout (0-100)
    - **target_levels**: Comma-separated target levels for level-based rollout
    - **target_user_ids**: Comma-separated target user IDs for user list rollout
    """
    try:
        flag = await service.create_feature_flag(
            name=flag_data.name,
            description=flag_data.description,
            rollout_type=flag_data.rollout_type,
            rollout_percentage=flag_data.rollout_percentage,
            target_levels=flag_data.target_levels,
            target_user_ids=flag_data.target_user_ids,
            created_by=flag_data.created_by
        )
        return FeatureFlagResponse(**flag)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[FeatureFlagResponse])
async def list_feature_flags(
    enabled_only: bool = Query(False, description="Only return enabled flags"),
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    List all feature flags
    
    - **enabled_only**: Filter to only show enabled flags
    """
    flags = await service.list_feature_flags(enabled_only=enabled_only)
    return [FeatureFlagResponse(**flag) for flag in flags]


@router.get("/{name}", response_model=FeatureFlagResponse)
async def get_feature_flag(
    name: str,
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Get a specific feature flag by name
    
    - **name**: Feature flag name
    """
    flag = await service.get_feature_flag(name)
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    return FeatureFlagResponse(**flag)


@router.put("/{name}", response_model=FeatureFlagResponse)
async def update_feature_flag(
    name: str,
    flag_data: FeatureFlagUpdate,
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Update an existing feature flag
    
    - **name**: Feature flag name
    - **enabled**: Enable/disable the flag
    - **rollout_type**: Rollout strategy
    - **rollout_percentage**: Percentage for rollout (0-100)
    - **target_levels**: Comma-separated target levels
    - **target_user_ids**: Comma-separated target user IDs
    """
    try:
        flag = await service.update_feature_flag(
            name=name,
            enabled=flag_data.enabled,
            rollout_type=flag_data.rollout_type,
            rollout_percentage=flag_data.rollout_percentage,
            target_levels=flag_data.target_levels,
            target_user_ids=flag_data.target_user_ids,
            updated_by=flag_data.updated_by
        )
        if not flag:
            raise HTTPException(status_code=404, detail="Feature flag not found")
        return FeatureFlagResponse(**flag)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{name}")
async def delete_feature_flag(
    name: str,
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Delete a feature flag
    
    - **name**: Feature flag name
    """
    try:
        success = await service.delete_feature_flag(name)
        if not success:
            raise HTTPException(status_code=404, detail="Feature flag not found")
        return {"message": "Feature flag deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/check", response_model=FeatureFlagCheckResponse)
async def check_feature_flag(
    check_data: FeatureFlagCheck,
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Check if a feature flag is enabled for a specific user
    
    - **name**: Feature flag name
    - **user_id**: User ID for user-specific checks
    - **user_level**: User level (S/A/B/C/D)
    """
    flag = await service.get_feature_flag(check_data.name)
    if not flag:
        return FeatureFlagCheckResponse(
            name=check_data.name,
            enabled=False,
            rollout_type="unknown",
            user_matches=False,
            reason="Feature flag not found"
        )
    
    is_enabled = await service.is_enabled(
        name=check_data.name,
        user_id=check_data.user_id,
        user_level=check_data.user_level
    )
    
    # Determine reason
    if not flag['enabled']:
        reason = "Feature flag is disabled"
    elif flag['rollout_type'] == RolloutType.ALL:
        reason = "Enabled for all users"
    elif flag['rollout_type'] == RolloutType.PERCENTAGE:
        reason = f"Percentage-based rollout ({flag['rollout_percentage']}%)"
    elif flag['rollout_type'] == RolloutType.LEVEL:
        reason = f"Level-based rollout (target levels: {flag['target_levels']})"
    elif flag['rollout_type'] == RolloutType.USER_LIST:
        reason = "User list-based rollout"
    else:
        reason = "Unknown rollout type"
    
    return FeatureFlagCheckResponse(
        name=check_data.name,
        enabled=is_enabled,
        rollout_type=flag['rollout_type'],
        user_matches=is_enabled,
        reason=reason
    )


@router.get("/{name}/audit")
async def get_feature_flag_audit_log(
    name: str,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of log entries"),
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Get audit log for a feature flag
    
    - **name**: Feature flag name
    - **limit**: Maximum number of log entries (1-100)
    """
    flag = await service.get_feature_flag(name)
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    
    audit_log = await service.get_audit_log(flag['id'], limit)
    return {
        "feature_flag_id": flag['id'],
        "feature_flag_name": name,
        "audit_log": audit_log
    }


@router.post("/cache/clear")
async def clear_cache(
    service: FeatureFlagService = Depends(lambda: feature_flag_service)
):
    """
    Clear the feature flag cache
    
    This endpoint is useful for forcing a cache refresh after database updates.
    """
    service.clear_cache()
    return {"message": "Feature flag cache cleared successfully"}