
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

@router.get(
    "/{user_id}/data-export",
    summary="用户 + 画像 + 记忆导出（供 admin 画像页等）",
    description=(
        "返回 ``user``、``profile``、``memories``。``profile`` 含与 "
        "``scripts/init.sql`` / Admin 一致的画像分字段，包括 "
        "``initiation_score``、``emotion_score``、``retention_score``、``dependency_score``、"
        "``loneliness_score``、``trigger_threshold``、``score_stage``、``score_updated_at``；"
        "其中 ``initiation_score`` / ``trigger_threshold`` 由 ``profile_score_worker``（D4-4）"
        "在 ``SCORE_WORKER_ENABLED=true`` 时周期性写回。"
    ),
)
async def data_export(user_id: str, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(text("SELECT * FROM users WHERE id=:uid"), {"uid": user_id})).fetchone()
    profile = (await db.execute(text("SELECT * FROM user_profiles WHERE user_id=:uid"), {"uid": user_id})).fetchone()
    memories = (await db.execute(text("SELECT id,memory_type,content,importance_score,created_at FROM memories WHERE user_id=:uid AND is_active=true"), {"uid": user_id})).fetchall()
    return {
        "user": dict(user._mapping) if user else None,
        "profile": dict(profile._mapping) if profile else None,
        "memories": [dict(m._mapping) for m in memories],
    }

@router.post("/{user_id}/risk-events")
async def create_risk_event(user_id: str, db: AsyncSession = Depends(get_db)):
    return {"status": "ok", "user_id": user_id}
