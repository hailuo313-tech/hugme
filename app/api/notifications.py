from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from services.notification_content import build_outbound_text
from services.minor_protection import MINOR_BLOCK_DETAIL, should_block_push
from services.telegram_send import send_telegram_text, telegram_chat_id_from_external
from services.mobile_push_service import get_mobile_push_service

router = APIRouter()

ALLOWED_CHANNELS = {"telegram", "android", "ios"}
ALLOWED_STATUSES = {"pending", "sending", "sent", "failed", "cancelled"}
DAILY_LIMIT = 1
WEEKLY_LIMIT = 3


class NotificationSchedule(BaseModel):
    user_id: str
    channel: str = "telegram"
    notification_type: str = Field(..., min_length=1, max_length=50)
    payload: dict = Field(default_factory=dict)
    scheduled_at: Optional[datetime] = None


class NotificationSendNow(BaseModel):
    user_id: str
    channel: str = "telegram"
    notification_type: str = Field(..., min_length=1, max_length=50)
    payload: dict = Field(default_factory=dict)
    # 移动端推送专用字段
    device_token: Optional[str] = None  # 设备令牌（移动端推送必需）
    platform: Optional[str] = None  # 平台类型（"android" 或 "ios"，移动端推送必需）


class NotificationCancel(BaseModel):
    reason: str = "cancelled_by_operator"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}") from exc


def _dedupe_key(user_id: str, notification_type: str, scheduled_at: datetime, payload: dict) -> str:
    strategy = payload.get("strategy") or notification_type
    tier = payload.get("tier") or "generic"
    return f"{strategy}:{tier}:{user_id}:{scheduled_at.date().isoformat()}"


async def _get_user(db: AsyncSession, user_id: str):
    row = (await db.execute(
        text(
            """
            SELECT id, channel, external_id, status, notification_opt_in,
                   opt_out_marketing, is_minor_suspected, risk_level, timezone
            FROM users
            WHERE id = :uid
            """
        ),
        {"uid": user_id},
    )).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


async def _assert_eligible(db: AsyncSession, user, channel: str):
    if channel not in ALLOWED_CHANNELS:
        raise HTTPException(status_code=422, detail="Unsupported notification channel")
    if user["status"] != "active":
        raise HTTPException(status_code=409, detail="User is not active")
    if not user["notification_opt_in"]:
        raise HTTPException(status_code=409, detail="User notification_opt_in is false")
    if user["opt_out_marketing"]:
        raise HTTPException(status_code=409, detail="User opted out of marketing")
    if should_block_push(is_minor_suspected=bool(user["is_minor_suspected"])):
        raise HTTPException(status_code=409, detail=MINOR_BLOCK_DETAIL)
    if user["risk_level"] in {"high", "critical"}:
        raise HTTPException(status_code=409, detail="High-risk users require handoff review")

    open_handoff = (await db.execute(
        text(
            """
            SELECT 1
            FROM handoff_tasks
            WHERE user_id = :uid
              AND closed_at IS NULL
              AND status IN ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')
            LIMIT 1
            """
        ),
        {"uid": user["id"]},
    )).fetchone()
    if open_handoff:
        raise HTTPException(status_code=409, detail="User has open handoff task")


async def _assert_frequency(db: AsyncSession, user_id: str, scheduled_at: datetime):
    day_start = scheduled_at - timedelta(hours=24)
    week_start = scheduled_at - timedelta(days=7)
    counts = (await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE scheduled_at >= :day_start) AS daily_count,
                COUNT(*) FILTER (WHERE scheduled_at >= :week_start) AS weekly_count
            FROM notification_tasks
            WHERE user_id = :uid
              AND notification_type = 'silent_reactivation'
              AND status IN ('pending', 'sending', 'sent')
            """
        ),
        {"uid": user_id, "day_start": day_start, "week_start": week_start},
    )).mappings().one()
    if counts["daily_count"] >= DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="Daily notification limit reached")
    if counts["weekly_count"] >= WEEKLY_LIMIT:
        raise HTTPException(status_code=429, detail="Weekly notification limit reached")


async def _assert_dedupe(db: AsyncSession, user_id: str, dedupe_key: str):
    existing = (await db.execute(
        text(
            """
            SELECT id, status
            FROM notification_tasks
            WHERE user_id = :uid
              AND notification_type = 'silent_reactivation'
              AND payload ->> 'dedupe_key' = :dedupe_key
              AND status IN ('pending', 'sending', 'sent')
            LIMIT 1
            """
        ),
        {"uid": user_id, "dedupe_key": dedupe_key},
    )).mappings().fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Duplicate notification task", "task_id": str(existing["id"])},
        )


async def _insert_notification_task(
    db: AsyncSession,
    *,
    user_id: str,
    channel: str,
    notification_type: str,
    payload: dict,
    scheduled_at: datetime,
    status: str,
) -> str:
    task_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO notification_tasks
                (id, user_id, channel, notification_type, payload, scheduled_at, status)
            VALUES
                (:id, :user_id, :channel, :notification_type, CAST(:payload AS jsonb), :scheduled_at, :status)
            """
        ),
        {
            "id": task_id,
            "user_id": user_id,
            "channel": channel,
            "notification_type": notification_type,
            "payload": __import__("json").dumps(payload),
            "scheduled_at": scheduled_at,
            "status": status,
        },
    )
    return task_id


async def _mark_send_now_failed(db: AsyncSession, task_id: str, reason: str) -> None:
    await db.execute(
        text(
            """
            UPDATE notification_tasks
            SET status = 'failed',
                failure_reason = :reason
            WHERE id = :id AND status = 'sending'
            """
        ),
        {"id": task_id, "reason": reason},
    )
    await db.commit()


@router.post("/schedule", status_code=202)
async def schedule_notification(
    data: NotificationSchedule,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = str(_as_uuid(data.user_id, "user_id"))
    scheduled_at = (data.scheduled_at or _utcnow()).replace(tzinfo=None)
    user = await _get_user(db, user_id)
    await _assert_eligible(db, user, data.channel)

    payload = dict(data.payload or {})
    if data.notification_type == "silent_reactivation":
        await _assert_frequency(db, user_id, scheduled_at)
        dedupe_key = payload.get("dedupe_key") or _dedupe_key(user_id, data.notification_type, scheduled_at, payload)
        payload["dedupe_key"] = dedupe_key
        await _assert_dedupe(db, user_id, dedupe_key)

    task_id = await _insert_notification_task(
        db,
        user_id=user_id,
        channel=data.channel,
        notification_type=data.notification_type,
        payload=payload,
        scheduled_at=scheduled_at,
        status="pending",
    )
    await db.commit()

    trace_id = getattr(request.state, "trace_id", None)
    logger.bind(
        trace_id=trace_id,
        notification_id=task_id,
        user_id=user_id,
        notification_type=data.notification_type,
        scheduled_at=scheduled_at.isoformat(),
    ).info("notification.task.scheduled")

    return {
        "notification_id": task_id,
        "status": "pending",
        "scheduled_at": scheduled_at.isoformat(),
        "payload": payload,
    }


@router.post("/send-now", status_code=200)
async def send_notification_now(
    data: NotificationSendNow,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = str(_as_uuid(data.user_id, "user_id"))
    scheduled_at = _utcnow()
    user = await _get_user(db, user_id)
    await _assert_eligible(db, user, data.channel)

    payload = dict(data.payload or {})
    if data.notification_type == "silent_reactivation":
        await _assert_frequency(db, user_id, scheduled_at)
        dedupe_key = payload.get("dedupe_key") or _dedupe_key(
            user_id, data.notification_type, scheduled_at, payload
        )
        payload["dedupe_key"] = dedupe_key
        await _assert_dedupe(db, user_id, dedupe_key)

    body = build_outbound_text(
        notification_type=data.notification_type,
        payload=payload,
    )
    if body is None:
        raise HTTPException(status_code=422, detail="Unsupported notification_type")

    task_id = await _insert_notification_task(
        db,
        user_id=user_id,
        channel=data.channel,
        notification_type=data.notification_type,
        payload=payload,
        scheduled_at=scheduled_at,
        status="sending",
    )
    await db.commit()

    trace_id = getattr(request.state, "trace_id", None)
    
    # 根据不同的 channel 处理发送逻辑
    if data.channel == "telegram":
        chat_id = telegram_chat_id_from_external(user["external_id"])
        if chat_id is None:
            await _mark_send_now_failed(db, task_id, "no_telegram_chat_id")
            raise HTTPException(
                status_code=409,
                detail={"message": "No Telegram chat id", "notification_id": task_id},
            )
        if not settings.TELEGRAM_BOT_TOKEN:
            await _mark_send_now_failed(db, task_id, "telegram_bot_token_missing")
            raise HTTPException(
                status_code=503,
                detail={"message": "Telegram bot token missing", "notification_id": task_id},
            )

        message_id = await send_telegram_text(
            chat_id=chat_id,
            text_content=body,
            trace_id=trace_id,
            parse_mode=None,
        )
        if message_id is None:
            await _mark_send_now_failed(db, task_id, "telegram_send_rejected")
            raise HTTPException(
                status_code=502,
                detail={"message": "Telegram send rejected", "notification_id": task_id},
            )

        await db.execute(
            text(
                """
                UPDATE notification_tasks
                SET status = 'sent',
                    sent_at = NOW(),
                    failure_reason = NULL
                WHERE id = :id AND status = 'sending'
                """
            ),
            {"id": task_id},
        )
        await db.commit()

        logger.bind(
            trace_id=trace_id,
            notification_id=task_id,
            user_id=user_id,
            notification_type=data.notification_type,
            telegram_message_id=message_id,
        ).info("notification.send_now.sent")

        return {
            "notification_id": task_id,
            "status": "sent",
            "sent_at": _utcnow().isoformat(),
            "telegram_message_id": message_id,
            "payload": payload,
        }
    
    elif data.channel in {"android", "ios"}:
        # 移动端推送
        if not data.device_token:
            await _mark_send_now_failed(db, task_id, "device_token_missing")
            raise HTTPException(
                status_code=422,
                detail={"message": "device_token is required for mobile push", "notification_id": task_id},
            )
        
        if not data.platform:
            await _mark_send_now_failed(db, task_id, "platform_missing")
            raise HTTPException(
                status_code=422,
                detail={"message": "platform is required for mobile push", "notification_id": task_id},
            )
        
        # 解析通知标题和内容
        title = payload.get("title", "ERIS")
        message_body = payload.get("body", body)
        
        push_service = get_mobile_push_service()
        result = await push_service.send_notification(
            device_token=data.device_token,
            platform=data.platform,
            title=title,
            body=message_body,
            data=payload,
            notification_id=task_id,
        )
        
        if result.success:
            await db.execute(
                text(
                    """
                    UPDATE notification_tasks
                    SET status = 'sent',
                        sent_at = NOW(),
                        failure_reason = NULL
                    WHERE id = :id AND status = 'sending'
                    """
                ),
                {"id": task_id},
            )
            await db.commit()
            
            logger.bind(
                trace_id=trace_id,
                notification_id=task_id,
                user_id=user_id,
                notification_type=data.notification_type,
                provider=result.provider,
                message_id=result.message_id,
            ).info("notification.send_now.sent")
            
            return {
                "notification_id": task_id,
                "status": "sent",
                "sent_at": _utcnow().isoformat(),
                "provider": result.provider,
                "message_id": result.message_id,
                "payload": payload,
            }
        else:
            await _mark_send_now_failed(db, task_id, result.error_message or "push_failed")
            raise HTTPException(
                status_code=502,
                detail={"message": result.error_message, "notification_id": task_id},
            )
    
    else:
        await _mark_send_now_failed(db, task_id, "unsupported_channel")
        raise HTTPException(
            status_code=422,
            detail={"message": "Unsupported channel", "notification_id": task_id},
        )


@router.get("/tasks")
async def list_notification_tasks(
    status: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    if status and status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    params = {"limit": limit}
    filters = []
    if status:
        filters.append("nt.status = :status")
        params["status"] = status
    if user_id:
        filters.append("nt.user_id = :user_id")
        params["user_id"] = str(_as_uuid(user_id, "user_id"))
    where = "WHERE " + " AND ".join(filters) if filters else ""
    rows = (await db.execute(
        text(
            f"""
            SELECT nt.*, u.external_id, u.timezone, u.notification_opt_in, u.opt_out_marketing
            FROM notification_tasks nt
            LEFT JOIN users u ON u.id = nt.user_id
            {where}
            ORDER BY nt.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    )).mappings().all()
    return [dict(row) for row in rows]


@router.post("/tasks/{task_id}/cancel")
async def cancel_notification_task(
    task_id: str,
    data: NotificationCancel,
    db: AsyncSession = Depends(get_db),
):
    task_uuid = str(_as_uuid(task_id, "task_id"))
    result = await db.execute(
        text(
            """
            UPDATE notification_tasks
            SET status = 'cancelled',
                failure_reason = :reason
            WHERE id = :id
              AND status = 'pending'
            RETURNING id
            """
        ),
        {"id": task_uuid, "reason": data.reason},
    )
    row = result.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Pending notification task not found")
    return {"notification_id": task_uuid, "status": "cancelled"}


@router.get("/logs")
async def notification_logs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        text(
            """
            SELECT id, user_id, channel, notification_type, status, scheduled_at,
                   sent_at, failure_reason, created_at
            FROM notification_tasks
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
    )).mappings().all()
    return [dict(row) for row in rows]
