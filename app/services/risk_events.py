"""risk_events 表读写 + risk_level 派生（§14.2 / V001-P0-3）。"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def risk_level_from_score(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 40:
        return "elevated"
    return "normal"


async def insert_risk_event(
    db: AsyncSession,
    *,
    user_id: str,
    risk_type: str,
    severity: str = "P0",
    trigger_message_id: Optional[str] = None,
    description: Optional[str] = None,
    commit: bool = True,
) -> str:
    event_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO risk_events (
              id, user_id, risk_type, severity,
              trigger_message_id, description
            ) VALUES (
              :id, :uid, :rtype, :sev, :mid, :desc
            )
            """
        ),
        {
            "id": event_id,
            "uid": user_id,
            "rtype": risk_type,
            "sev": severity,
            "mid": trigger_message_id,
            "desc": description,
        },
    )
    if commit:
        await db.commit()
    return event_id


async def sync_user_risk_from_profile_score(
    db: AsyncSession,
    *,
    user_id: str,
    risk_score: int,
    commit: bool = False,
) -> str:
    """同事务更新 users.risk_level（V001 P1 与危机协议共用）。"""
    level = risk_level_from_score(int(risk_score))
    await db.execute(
        text("UPDATE users SET risk_level=:rl, updated_at=NOW() WHERE id=:uid"),
        {"rl": level, "uid": user_id},
    )
    if commit:
        await db.commit()
    return level


async def list_risk_events_for_user(
    db: AsyncSession,
    user_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, user_id, risk_type, severity, trigger_message_id,
                       description, handled_by, handled_at, resolution, created_at
                FROM risk_events
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"uid": user_id, "lim": limit},
        )
    ).fetchall()
    return [dict(r._mapping) for r in rows]
