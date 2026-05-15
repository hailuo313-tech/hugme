
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from pydantic import BaseModel
from typing import Optional
import uuid

router = APIRouter()

class OnboardingStep(BaseModel):
    channel: str
    external_user_id: str
    step: int
    answer: str

class NotificationSettings(BaseModel):
    notification_opt_in: Optional[bool] = None
    opt_out_marketing: Optional[bool] = None


class RiskEventCreate(BaseModel):
    risk_type: str
    severity: Optional[str] = "P1"
    trigger_message_id: Optional[str] = None
    description: Optional[str] = None

@router.post("/onboarding")
async def onboarding(data: OnboardingStep, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id FROM users WHERE channel=:ch AND external_id=:eid"),
        {"ch": data.channel, "eid": data.external_user_id}
    )
    user = result.fetchone()
    if not user:
        uid = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO users (id,channel,external_id) VALUES (:id,:ch,:eid)"),
            {"id": uid, "ch": data.channel, "eid": data.external_user_id}
        )
        await db.execute(text("INSERT INTO user_profiles (user_id) VALUES (:uid)"), {"uid": uid})
        await db.commit()
    completed = data.step >= 5
    return {"step": data.step, "next_step": data.step + 1 if not completed else None, "completed": completed}

@router.get("/{user_id}")
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM users WHERE id=:uid"), {"uid": user_id})
    user = result.fetchone()
    if not user:
        raise HTTPException(404, "User not found")
    return dict(user._mapping)

@router.patch("/{user_id}/notification-settings")
async def update_notification_settings(user_id: str, data: NotificationSettings, db: AsyncSession = Depends(get_db)):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if updates:
        set_clause = ", ".join([f"{k}=:{k}" for k in updates])
        updates["uid"] = user_id
        await db.execute(text(f"UPDATE users SET {set_clause} WHERE id=:uid"), updates)
        await db.commit()
    return {"status": "ok"}

@router.get("/{user_id}/data-export")
async def data_export(user_id: str, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(text("SELECT * FROM users WHERE id=:uid"), {"uid": user_id})).fetchone()
    profile = (await db.execute(text("SELECT * FROM user_profiles WHERE user_id=:uid"), {"uid": user_id})).fetchone()
    memories = (await db.execute(text("SELECT id,memory_type,content,importance_score,created_at FROM memories WHERE user_id=:uid AND is_active=true"), {"uid": user_id})).fetchall()
    return {
        "user": dict(user._mapping) if user else None,
        "profile": dict(profile._mapping) if profile else None,
        "memories": [dict(m._mapping) for m in memories],
    }

@router.post("/{user_id}/risk-events", status_code=201)
async def create_risk_event(
    user_id: str,
    data: RiskEventCreate,
    db: AsyncSession = Depends(get_db),
):
    """V001-P0-3：写入 risk_events；按 severity 提升 risk_score 并派生 users.risk_level。"""
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a valid UUID")

    user = (
        await db.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.trigger_message_id:
        try:
            uuid.UUID(data.trigger_message_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="trigger_message_id must be a valid UUID"
            )

    from services.risk_events import (
        bump_profile_risk_score,
        insert_risk_event,
        severity_to_risk_score,
    )

    severity = (data.severity or "P1").upper()
    score = severity_to_risk_score(severity)

    event_id = await insert_risk_event(
        db,
        user_id=user_id,
        risk_type=data.risk_type,
        severity=severity,
        trigger_message_id=data.trigger_message_id,
        description=data.description,
        commit=False,
    )
    level = await bump_profile_risk_score(
        db, user_id=user_id, risk_score=score, commit=False
    )
    await db.commit()

    return {
        "status": "created",
        "user_id": user_id,
        "risk_event_id": event_id,
        "risk_score": score,
        "risk_level": level,
    }


@router.get("/{user_id}/risk-events")
async def list_user_risk_events(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """V001-P0-3：查询用户风险事件列表。"""
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a valid UUID")

    user = (
        await db.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from services.risk_events import list_risk_events_for_user

    items = await list_risk_events_for_user(db, user_id)
    return {"user_id": user_id, "items": items, "total": len(items)}
