"""V001-P0-2 + 危机关键词治理：检测、误报过滤、多语言安全话术、协议落库。"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.risk_events import bump_profile_risk_score, insert_risk_event

# ── 高危表达（命中后仍要经过误报/否定过滤）────────────────────────

_CRISIS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        # English
        r"\b(kill\s+myself|killing\s+myself|suicide|suicidal|self[- ]?harm|self[- ]?injur)\b",
        r"\b(want\s+to\s+die|wanna\s+die|wish\s+i\s+was\s+dead|wish\s+i\s+were\s+dead)\b",
        r"\b(don'?t\s+want\s+to\s+live|do\s+not\s+want\s+to\s+live)\b",
        r"\b(end\s+my\s+life|take\s+my\s+life|better\s+off\s+dead)\b",
        r"\b(no\s+reason\s+to\s+live|can'?t\s+go\s+on|cannot\s+go\s+on)\b",
        r"\b(hurt\s+myself|harm\s+myself)\b",
        # Spanish (common TG locales)
        r"\b(quiero\s+morir|no\s+quiero\s+vivir|suicid(io|arme)|acabar\s+con\s+mi\s+vida)\b",
        # Chinese
        r"想死|不想活|不想活了|活不下去|活不下去了|去死|不如死|一死了之|寻短见|轻生",
        r"自杀|自残|自伤|自刎|割腕|跳楼|了结|结束生命|伤害自己|结束一切",
    )
)

# 俗语/游戏/否定语境 — 命中则**不**视为危机（误报治理）
_FALSE_POSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r"笑死|累死|困死|吓死|热死|气死|饿死|闲死|冷死|渴死",
        r"死党|死机|死线|死板|死胡同|死循环|死磕",
        r"要死不死|差点死|没死|不会死",
        r"\b(dying\s+to\s+meet|dying\s+for|kill\s+time|bored\s+to\s+death)\b",
        r"\b(death\s+of|after\s+death|game\s+over|if\s+i\s+die\s+in)\b",
    )
)

# 明确否定自杀意图（英文）
_NEGATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(don'?t|do\s+not|not|never|no\s+longer)\s+.{0,20}(want\s+to\s+die|kill\s+myself|suicide|end\s+my\s+life)\b",
        r"\b(wouldn'?t|won'?t)\s+.{0,15}(kill\s+myself|end\s+my\s+life)\b",
        r"不是想死|不想死|不会去死|没有想死",
    )
)

CRISIS_SAFETY_REPLIES: dict[str, str] = {
    "en": (
        "I'm really sorry you're feeling this way. You're not alone, and you deserve "
        "support right now.\n\n"
        "If you are in immediate danger, please contact local emergency services.\n"
        "Crisis lines: US/Canada 988 · UK Samaritans 116 123 · "
        "China psychological aid 400-161-9995.\n\n"
        "I've alerted our care team — a human will follow up with you as soon as possible. "
        "Until then, please stay safe."
    ),
    "zh": (
        "我很抱歉你正在承受这些，你并不孤单，此刻你值得被认真倾听和陪伴。\n\n"
        "若你处于紧急危险中，请立即联系当地急救或报警。\n"
        "心理援助：中国 400-161-9995 · 北京 010-82951332 · 上海 021-63798925。\n\n"
        "我已通知人工关怀团队，会尽快有人联系你。在这之前，请尽量待在安全的地方。"
    ),
    "es": (
        "Lamento mucho que te sientas así. No estás solo/a y mereces apoyo ahora mismo.\n\n"
        "Si estás en peligro inmediato, contacta a los servicios de emergencia locales.\n"
        "Líneas de crisis: 024 (España) · 911 (LATAM, según tu país).\n\n"
        "He avisado a nuestro equipo de cuidado; una persona te contactará lo antes posible. "
        "Hasta entonces, por favor cuídate."
    ),
}

# 向后兼容单测 / 旧引用
CRISIS_SAFETY_REPLY = CRISIS_SAFETY_REPLIES["en"]


@dataclass(frozen=True)
class CrisisHandleResult:
    safety_reply: str
    risk_event_id: str
    handoff_task_id: str
    reply_language: str


def _normalize_user_text(user_text: str) -> str:
    return re.sub(r"\s+", " ", (user_text or "").strip())


def detect_crisis_language(user_text: str) -> str:
    """轻量语种选择（仅用于安全话术，不做通用 NLP）。"""
    text = user_text or ""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= 2:
        return "zh"
    if cjk == 1 and len(text.strip()) <= 12:
        return "zh"
    lower = text.lower()
    if re.search(
        r"[ñáéíóúü]|quiero\s+morir|suicid|no\s+quiero\s+vivir|acabar\s+con",
        lower,
    ):
        return "es"
    return "en"


def pick_crisis_safety_reply(user_text: str) -> tuple[str, str]:
    """返回 (reply_text, language_code)。"""
    lang = detect_crisis_language(user_text)
    return CRISIS_SAFETY_REPLIES.get(lang, CRISIS_SAFETY_REPLIES["en"]), lang


def _is_false_positive(normalized: str) -> bool:
    return any(p.search(normalized) for p in _FALSE_POSITIVE_PATTERNS)


def _has_negation(normalized: str) -> bool:
    return any(p.search(normalized) for p in _NEGATION_PATTERNS)


def detect_crisis_in_text(user_text: str) -> bool:
    normalized = _normalize_user_text(user_text)
    if not normalized:
        return False
    if _is_false_positive(normalized):
        return False
    if not any(p.search(normalized) for p in _CRISIS_PATTERNS):
        return False
    if _has_negation(normalized):
        return False
    return True


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

    safety_reply, reply_lang = pick_crisis_safety_reply(user_text)

    handoff_id = str(uuid.uuid4())
    crisis_score = 95

    risk_event_id = await insert_risk_event(
        db,
        user_id=user_id,
        risk_type="crisis",
        severity="P0",
        trigger_message_id=trigger_message_id,
        description=(user_text or "")[:2000],
        commit=False,
    )

    await db.execute(
        text(
            """
            UPDATE user_profiles
            SET relationship_stage = 'S5',
                updated_at = NOW()
            WHERE user_id = :uid
            """
        ),
        {"uid": user_id},
    )

    await bump_profile_risk_score(
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
        reply_language=reply_lang,
    ).info("crisis.protocol.applied")

    return CrisisHandleResult(
        safety_reply=safety_reply,
        risk_event_id=risk_event_id,
        handoff_task_id=handoff_id,
        reply_language=reply_lang,
    )
