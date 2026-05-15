"""V001-P0-2：危机关键词检测 + 安全话术 + risk_event + P0 handoff + S5。"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.risk_events import sync_user_risk_from_profile_score

# 英文 + 中文高危表达（子串匹配，大小写不敏感）
_CRISIS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(kill\s+myself|suicide|self[- ]?harm|want\s+to\s+die|end\s+my\s+life)\b",
        r"\b(i\s+want\s+to\s+die|don't\s+want\s+to\s+live)\b",
        r"想死|不想活|自杀|自残|自伤|了结|结束生命|伤害自己",
    )
)

CRISIS_SAFETY_REPLY = (
    "I'm really sorry you're feeling this way. You're not alone, and you deserve support right now.\n\n"
    "If you are in immediate danger, please contact local emergency services.\n"
    "Crisis lines: US/Canada 988 · UK Samaritans 116 123 · "
    "China psychological aid 400-161-9995.\n\n"
    "I've alerted our care team — a human will follow up with you as soon as possible. "
    "Until then, please stay safe."
)


@dataclass(frozen=True)
class CrisisHandleResult:
    safety_reply: str
    risk_event_id: str
    handoff_task_id: str


def detect_crisis_in_text(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False
    return any(p.search(text) for p in _CRISIS_PATTERNS)


async def apply_crisis_protocol(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    user_text: str,
    trigger_message_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> CrisisHandleResult:
    """写 risk_events、升风险、S5、创建 P0 handoff、会话转 WAITING_OPERATOR。"""
    log = logger.bind(
        trace_id=trace_id,
        component="crisis",
        user_id=user_id,
        conversation_id=conversation_id,
    )

    risk_event_id = str(uuid.uuid4())
    handoff_id = str(uuid.uuid4())
    crisis_score = 95

    await db.execute(
        text(
            """
            INSERT INTO risk_events (
              id, user_id, risk_type, severity,
              trigger_message_id, description
            ) VALUES (
              :id, :uid, 'crisis', 'P0', :mid, :desc
            )
            """
        ),
        {
            "id": risk_event_id,
            "uid": user_id,
            "mid": trigger_message_id,
            "desc": (user_text or "")[:2000],
        },
    )

    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET relationship_stage = 'S5',
                risk_score = GREATEST(COALESCE(risk_score, 0), :score),
                updated_at = NOW()
            WHERE user_id = :uid
            """
        ),
        {"uid": user_id, "score": crisis_score},
    )

    await sync_user_risk_from_profile_score(
        db, user_id=user_id, risk_score=crisis_score, commit=False
    )

    await db.execute(
        text(
            """
            INSERT INTO handoff_tasks (
              id, user_id, conversation_id, priority, trigger_reason, status
            ) VALUES (
              :id, :uid, :cid, 'P0', 'crisis_keyword', 'WAITING_OPERATOR'
            )
            """
        ),
        {"id": handoff_id, "uid": user_id, "cid": conversation_id},
    )

    await db.execute(
        text(
            """
            UPDATE conversations
            SET state = 'WAITING_OPERATOR',
                handoff_count = COALESCE(handoff_count, 0) + 1,
                updated_at = NOW()
            WHERE id = :cid
            """
        ),
        {"cid": conversation_id},
    )

    await db.commit()

    log.bind(
        risk_event_id=risk_event_id,
        handoff_task_id=handoff_id,
    ).info("crisis.protocol.applied")

    return CrisisHandleResult(
        safety_reply=CRISIS_SAFETY_REPLY,
        risk_event_id=risk_event_id,
        handoff_task_id=handoff_id,
    )
