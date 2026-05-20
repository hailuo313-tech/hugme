from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

router = APIRouter()

ALLOWED_CHANNELS = {"telegram"}
ALLOWED_STATUSES = {"pending", "sending", "sent", "failed", "cancelled"}
DAILY_LIMIT = 1
WEEKLY_LIMIT = 3


class NotificationSchedule(BaseModel):
    user_id: str
    channel: str = "telegram"
    notification_type: str = Field(..., min_length=1, max_length=50)
    payload: dict = Field(default_factory=dict)
    scheduled_at: Optional[datetime] = None


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
    if user["is_minor_suspected"]:
        raise HTTPException(status_code=409, detail="User suspected minor")
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

    task_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO notification_tasks
                (id, user_id, channel, notification_type, payload, scheduled_at, status)
            VALUES
                (:id, :user_id, :channel, :notification_type, CAST(:payload AS jsonb), :scheduled_at, 'pending')
            """
        ),
        {
            "id": task_id,
            "user_id": user_id,
            "channel": data.channel,
            "notification_type": data.notification_type,
            "payload": __import__("json").dumps(payload),
            "scheduled_at": scheduled_at,
        },
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


@router.get("/tasks")
async def list_notification_tasks(
    status: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    if status and status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    params: dict[str, Any] = {"limit": limit}
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
