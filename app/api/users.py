
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from api.admin import require_operator
from core.database import get_db
from pydantic import BaseModel
import json
from datetime import date
from typing import Any, Mapping, Optional
import uuid

from services.profile_intake import age_from_preferences, normalize_country_code

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


class UserFreezeRequest(BaseModel):
    reason: Optional[str] = None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _profile_text(preferences: Mapping[str, Any], *keys: str) -> str | None:
    return _first_text(*(preferences.get(key) for key in keys))


def _profile_country(profile_data: Mapping[str, Any], preferences: Mapping[str, Any]) -> str | None:
    candidates = (
        profile_data.get("country_code"),
        preferences.get("country_code"),
        preferences.get("country"),
        preferences.get("geo_country"),
        preferences.get("ip_country"),
        preferences.get("detected_country_code"),
        preferences.get("detected_country"),
        preferences.get("inferred_country_code"),
        preferences.get("country_from_city"),
        preferences.get("work_country"),
        preferences.get("living_country"),
    )
    for candidate in candidates:
        code = normalize_country_code(candidate)
        if code:
            return code
    return None


def _profile_city(preferences: Mapping[str, Any]) -> str | None:
    return _profile_text(
        preferences,
        "current_city",
        "city",
        "user_city",
        "location",
        "work_city",
        "living_city",
        "hometown",
        "birth_city",
        "profile_city",
        "detected_city",
    )


def _profile_age(preferences: Mapping[str, Any]) -> int | None:
    age = age_from_preferences(preferences)
    if age is not None:
        return age
    for key in ("birth_year", "born_year", "year_of_birth"):
        raw_year = preferences.get(key)
        try:
            year = int(str(raw_year).strip())
        except (TypeError, ValueError):
            continue
        computed = date.today().year - year
        if 18 <= computed <= 100:
            return computed
    return None


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_profile_export(profile_row: Any) -> dict[str, Any] | None:
    if not profile_row:
        return None
    profile_data = dict(profile_row._mapping)
    preferences = _as_dict(profile_data.get("preferences"))
    country_code = _profile_country(profile_data, preferences)
    city = _profile_city(preferences)
    age = _profile_age(preferences)
    relationship_stage = _first_text(
        profile_data.get("relationship_stage"),
        preferences.get("relationship_stage"),
        preferences.get("stage"),
    ) or "S0"
    vip_level = _as_int(
        profile_data.get("vip_level")
        if profile_data.get("vip_level") is not None
        else preferences.get("vip_level"),
        default=0,
    )

    profile_data["preferences"] = preferences
    profile_data["country_code"] = country_code
    profile_data["city"] = city
    profile_data["age"] = age
    profile_data["relationship_stage"] = relationship_stage
    profile_data["vip_level"] = vip_level
    profile_data["user_level"] = _first_text(profile_data.get("user_level"), preferences.get("user_level"))
    return profile_data


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} must be a valid UUID"
        ) from exc

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


@router.post("/{user_id}/freeze")
async def freeze_user(
    user_id: str,
    data: UserFreezeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """P2：冻结用户，阻止继续 AI 会话与主动触达。"""
    uid = _validate_uuid(user_id, "user_id")
    reason = (data.reason if data else None) or "operator_freeze"

    row = (
        await db.execute(
            text(
                """
                UPDATE users
                SET status = 'frozen',
                    opt_out_marketing = TRUE,
                    updated_at = NOW()
                WHERE id = :uid
                RETURNING id, status
                """
            ),
            {"uid": uid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    conv_res = await db.execute(
        text(
            """
            UPDATE conversations
            SET state = 'FROZEN',
                updated_at = NOW()
            WHERE user_id = :uid
              AND state NOT IN ('CLOSED', 'ESCALATED', 'FROZEN')
            RETURNING id
            """
        ),
        {"uid": uid},
    )
    notification_res = await db.execute(
        text(
            """
            UPDATE notification_tasks
            SET status = 'cancelled',
                failure_reason = :reason
            WHERE user_id = :uid
              AND status IN ('pending', 'sending')
            RETURNING id
            """
        ),
        {"uid": uid, "reason": f"user_frozen:{reason[:100]}"},
    )
    schedule_res = await db.execute(
        text(
            """
            UPDATE message_schedules
            SET status = 'failed',
                failure_reason = :reason,
                updated_at = NOW()
            WHERE user_id = :uid
              AND status IN ('pending', 'scheduled', 'sending')
            RETURNING id
            """
        ),
        {"uid": uid, "reason": f"user_frozen:{reason[:100]}"},
    )
    await db.commit()

    return {
        "status": "frozen",
        "user_id": uid,
        "conversations_frozen": len(conv_res.fetchall()),
        "notifications_cancelled": len(notification_res.fetchall()),
        "schedules_cancelled": len(schedule_res.fetchall()),
    }

@router.get("/{user_id}/data-export")
async def data_export(user_id: str, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(text("SELECT * FROM users WHERE id=:uid"), {"uid": user_id})).fetchone()
    profile = (await db.execute(text("SELECT * FROM user_profiles WHERE user_id=:uid"), {"uid": user_id})).fetchone()
    memories = (await db.execute(text("SELECT id,memory_type,content,importance_score,created_at FROM memories WHERE user_id=:uid AND is_active=true"), {"uid": user_id})).fetchall()
    recent_messages = (
        await db.execute(
            text(
                """
                SELECT
                    m.id::text AS id,
                    m.sender_type,
                    m.content,
                    m.created_at
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.user_id = :uid
                  AND COALESCE(m.content, '') <> ''
                ORDER BY m.created_at DESC
                LIMIT 30
                """
            ),
            {"uid": user_id},
        )
    ).fetchall()
    return {
        "user": dict(user._mapping) if user else None,
        "profile": _normalize_profile_export(profile),
        "memories": [dict(m._mapping) for m in memories],
        "recent_messages": [dict(m._mapping) for m in recent_messages],
    }

@router.post("/{user_id}/risk-events", status_code=201)
async def create_risk_event(
    user_id: str,
    data: RiskEventCreate,
    db: AsyncSession = Depends(get_db),
):
    """V001-P0-3：写入 risk_events；按 severity 提升 risk_score 并派生 users.risk_level。"""
    _validate_uuid(user_id, "user_id")

    user = (
        await db.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.trigger_message_id:
        _validate_uuid(data.trigger_message_id, "trigger_message_id")

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
    _validate_uuid(user_id, "user_id")

    user = (
        await db.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id})
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from services.risk_events import list_risk_events_for_user

    items = await list_risk_events_for_user(db, user_id)
    return {"user_id": user_id, "items": items, "total": len(items)}
