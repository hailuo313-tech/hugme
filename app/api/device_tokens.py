"""
P4-10: 设备令牌管理 API

用于管理移动端设备令牌，支持注册、更新、查询和删除操作。
"""
from datetime import datetime
from typing import Optional, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

router = APIRouter()


class DeviceTokenRegister(BaseModel):
    """设备令牌注册请求"""
    user_id: str = Field(..., min_length=1)
    device_token: str = Field(..., min_length=1)
    platform: str = Field(..., pattern="^(android|ios)$")
    device_info: Optional[dict] = None  # 设备信息（型号、OS版本等）


class DeviceTokenUpdate(BaseModel):
    """设备令牌更新请求"""
    device_info: Optional[dict] = None


class PushTestRequest(BaseModel):
    """推送测试请求"""
    device_token: str = Field(..., min_length=1)
    platform: str = Field(..., pattern="^(android|ios)$")
    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=500)
    data: Optional[dict] = None


def _as_uuid(value: str, field_name: str) -> uuid.UUID:
    """转换为 UUID"""
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}") from exc


@router.post("/devices/register")
async def register_device_token(
    data: DeviceTokenRegister,
    db: AsyncSession = Depends(get_db),
):
    """
    注册设备令牌
    
    如果设备令牌已存在，则更新相关信息；否则创建新记录。
    """
    user_id = str(_as_uuid(data.user_id, "user_id"))
    
    # 检查设备令牌是否已存在
    existing = await db.execute(
        text(
            """
            SELECT id, user_id, platform
            FROM device_tokens
            WHERE device_token = :device_token
            LIMIT 1
            """
        ),
        {"device_token": data.device_token},
    )
    existing_row = existing.fetchone()
    
    if existing_row:
        # 更新现有记录
        await db.execute(
            text(
                """
                UPDATE device_tokens
                SET user_id = :user_id,
                    platform = :platform,
                    device_info = :device_info,
                    updated_at = NOW()
                WHERE device_token = :device_token
                """
            ),
            {
                "user_id": user_id,
                "platform": data.platform,
                "device_info": __import__("json").dumps(data.device_info or {}),
                "device_token": data.device_token,
            },
        )
        await db.commit()
        
        logger.bind(
            user_id=user_id,
            platform=data.platform,
            device_token=data.device_token[:20] + "...",
        ).info("device_token.updated")
        
        return {
            "status": "updated",
            "device_token": data.device_token,
            "user_id": user_id,
            "platform": data.platform,
        }
    else:
        # 创建新记录
        token_id = str(uuid.uuid4())
        await db.execute(
            text(
                """
                INSERT INTO device_tokens
                    (id, user_id, device_token, platform, device_info, created_at, updated_at)
                VALUES
                    (:id, :user_id, :device_token, :platform, :device_info, NOW(), NOW())
                """
            ),
            {
                "id": token_id,
                "user_id": user_id,
                "device_token": data.device_token,
                "platform": data.platform,
                "device_info": __import__("json").dumps(data.device_info or {}),
            },
        )
        await db.commit()
        
        logger.bind(
            user_id=user_id,
            platform=data.platform,
            device_token=data.device_token[:20] + "...",
        ).info("device_token.registered")
        
        return {
            "status": "registered",
            "device_token": data.device_token,
            "user_id": user_id,
            "platform": data.platform,
        }


@router.get("/devices")
async def list_device_tokens(
    user_id: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None, pattern="^(android|ios)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    查询设备令牌列表
    
    支持按用户 ID 和平台筛选。
    """
    params = {"limit": limit}
    filters = []
    
    if user_id:
        filters.append("user_id = :user_id")
        params["user_id"] = str(_as_uuid(user_id, "user_id"))
    
    if platform:
        filters.append("platform = :platform")
        params["platform"] = platform
    
    where = "WHERE " + " AND ".join(filters) if filters else ""
    
    rows = await db.execute(
        text(
            f"""
            SELECT id, user_id, device_token, platform, device_info, created_at, updated_at
            FROM device_tokens
            {where}
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    
    devices = []
    for row in rows.mappings().all():
        device = dict(row)
        # 解析 JSON 字段
        if device.get("device_info"):
            device["device_info"] = __import__("json").loads(device["device_info"])
        devices.append(device)
    
    return {
        "devices": devices,
        "count": len(devices),
    }


@router.get("/devices/{device_token}")
async def get_device_token(
    device_token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取单个设备令牌的详细信息
    """
    result = await db.execute(
        text(
            """
            SELECT id, user_id, device_token, platform, device_info, created_at, updated_at
            FROM device_tokens
            WHERE device_token = :device_token
            LIMIT 1
            """
        ),
        {"device_token": device_token},
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Device token not found")
    
    device = dict(row)
    # 解析 JSON 字段
    if device.get("device_info"):
        device["device_info"] = __import__("json").loads(device["device_info"])
    
    return device


@router.delete("/devices/{device_token}")
async def delete_device_token(
    device_token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除设备令牌
    
    通常在用户登出或卸载应用时调用。
    """
    result = await db.execute(
        text(
            """
            DELETE FROM device_tokens
            WHERE device_token = :device_token
            RETURNING user_id, platform
            """
        ),
        {"device_token": device_token},
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Device token not found")
    
    await db.commit()
    
    logger.bind(
        user_id=row[0],
        platform=row[1],
        device_token=device_token[:20] + "...",
    ).info("device_token.deleted")
    
    return {
        "status": "deleted",
        "device_token": device_token,
    }


@router.post("/test-push")
async def test_push_notification(
    data: PushTestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    测试推送通知
    
    用于管理界面测试推送功能是否正常工作。
    """
    from services.mobile_push_service import get_mobile_push_service
    
    push_service = get_mobile_push_service()
    result = await push_service.send_notification(
        device_token=data.device_token,
        platform=data.platform,
        title=data.title,
        body=data.body,
        data=data.data,
        notification_id=f"test-{uuid.uuid4()}",
    )
    
    if result.success:
        logger.bind(
            device_token=data.device_token[:20] + "...",
            platform=data.platform,
            title=data.title,
            message_id=result.message_id,
        ).info("test_push.success")
        
        return {
            "success": True,
            "provider": result.provider,
            "message_id": result.message_id,
            "device_token": data.device_token[:20] + "...",
        }
    else:
        logger.bind(
            device_token=data.device_token[:20] + "...",
            platform=data.platform,
            error=result.error_message,
        ).error("test_push.failed")
        
        return {
            "success": False,
            "error": result.error_message,
            "provider": result.provider,
            "device_token": data.device_token[:20] + "...",
        }


@router.get("/user/{user_id}/devices")
async def get_user_devices(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定用户的所有设备令牌
    
    用于向用户的所有设备发送推送。
    """
    user_uuid = str(_as_uuid(user_id, "user_id"))
    
    rows = await db.execute(
        text(
            """
            SELECT id, user_id, device_token, platform, device_info, created_at, updated_at
            FROM device_tokens
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            """
        ),
        {"user_id": user_uuid},
    )
    
    devices = []
    for row in rows.mappings().all():
        device = dict(row)
        # 解析 JSON 字段
        if device.get("device_info"):
            device["device_info"] = __import__("json").loads(device["device_info"])
        devices.append(device)
    
    return {
        "user_id": user_id,
        "devices": devices,
        "count": len(devices),
    }