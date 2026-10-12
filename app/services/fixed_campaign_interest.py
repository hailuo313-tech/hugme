"""AI-only interest classification for the fixed new-user campaign."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import text

from services.llm import chat
from services.mtproto.inbound_media import find_chat_media_file, guess_inbound_photo_media_type


TRIGGER_PREFIX = "fixed_campaign_interest:"
CAMPAIGN_RULE_ORDERS = (26, 27, 28, 29, 30, 31)
_POSITIVE_FALLBACK = re.compile(
    r"(?:\b(?:yes|yeah|yep|sure|send|want|interested|price|cost|pay|buy|vip|menu|"
    r"photo|pics?|video|call|one[- ]on[- ]one)\b|(?:我要|想要|可以|好的|发我|多少钱|"
    r"价格|购买|付款|图片|照片|视频|通话|菜单))",
    re.IGNORECASE,
)
_NEGATIVE_INTENT = re.compile(
    r"(?:\b(?:no|nope|nah|never|stop|unsubscribe|cancel)\b|"
    r"\b(?:not interested|don['’]?t want|do not want|don['’]?t send|leave me alone|"
    r"can['’]?t pay|cannot pay|no money|too expensive)\b|"
    r"\b(?:no me interesa|no quiero|no env[ií]es|d[eé]jame|sin dinero|muy caro)\b|"
    r"\b(?:n[aã]o quero|n[aã]o tenho interesse|n[aã]o envie|sem dinheiro|muito caro)\b|"
    r"(?:不要|不需要|没兴趣|不感兴趣|别发|停止|取消|没钱|太贵|不用了))",
    re.IGNORECASE,
)
_CAMPAIGN_OPTION_INTENT = re.compile(r"^\s*[123]\s*[.!?。！？]*\s*$")
_PRICE_INTENT = re.compile(
    r"(?:^\s*[$€£¥]\s*[?？]*\s*$|\b(?:price|cost|fee|fees|rate|rates|how much|"
    r"cu[aá]nto|precio|pre[cç]o|valor|honorarios)\b|(?:多少钱|价格|费用|怎么收费))",
    re.IGNORECASE,
)


async def _understand_media(path: Path, content_type: str) -> str:
    """Describe an image or transcribe a voice note for the intent classifier."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or not path.is_file() or path.stat().st_size <= 0:
        return ""
    mime = guess_inbound_photo_media_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    is_audio = content_type in {"voice", "audio"} or mime.startswith("audio/")
    model = "openai/gpt-4o-audio-preview" if is_audio else "openai/gpt-4o-mini"
    media_part = (
        {"type": "input_audio", "input_audio": {"data": encoded, "format": path.suffix.lstrip(".") or "ogg"}}
        if is_audio
        else {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
    )
    prompt = (
        "Transcribe this voice message, then state whether it expresses interest in photos, videos, "
        "a private call, VIP access, price, purchase, or payment. Preserve explicit rejection."
        if is_audio
        else "Describe this image and visible text. State whether it shows payment proof or interest in "
        "photos, videos, a private call, VIP access, price, purchase, or payment."
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "temperature": 0, "max_tokens": 50, "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}, media_part]}
                ]},
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        logger.bind(path=str(path), content_type=content_type, error_type=type(exc).__name__).warning(
            "fixed_campaign_interest.media_understanding_failed"
        )
        return ""


def _parse_json_object(value: str) -> dict[str, Any] | None:
    cleaned = str(value or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def evaluate_fixed_campaign_interest(
    db: Any,
    *,
    user_id: str,
    conversation_id: str,
    user_text: str,
    trace_id: str,
    message_id: str | None = None,
) -> bool:
    """Classify campaign replies and create one open interest task when positive."""
    content = str(user_text or "").strip()
    if content in {"[sticker]", "[emoji]"}:
        return False

    latest_message = (
        await db.execute(
            text(
                """
                SELECT id::text, COALESCE(content_type, 'text')
                FROM messages
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND sender_type = 'user'
                  AND (CAST(:message_id AS uuid) IS NULL OR id = CAST(:message_id AS uuid))
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"cid": conversation_id, "message_id": message_id},
        )
    ).fetchone()
    media_context = ""
    if latest_message and str(latest_message[1]) in {"image", "photo", "voice", "audio"}:
        media_path = find_chat_media_file(str(latest_message[0]))
        if media_path is not None:
            media_context = await _understand_media(media_path, str(latest_message[1]))
    effective_content = "\n".join(part for part in (content, media_context) if part).strip()
    if not effective_content or effective_content in {"[media]", "[photo]", "[audio]", "[voice]", "[video]"}:
        return False
    if _NEGATIVE_INTENT.search(effective_content):
        logger.bind(user_id=user_id, conversation_id=conversation_id).info(
            "fixed_campaign_interest.explicit_negative"
        )
        return False

    campaign_row = (
        await db.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM fixed_auto_reply_jobs j
                  JOIN fixed_auto_reply_rules r ON r.id = j.rule_id
                  WHERE j.user_id = CAST(:uid AS uuid)
                    AND r.sort_order = ANY(:orders)
                )
                """
            ),
            {"uid": user_id, "orders": list(CAMPAIGN_RULE_ORDERS)},
        )
    ).scalar()
    if not campaign_row:
        return False

    existing = (
        await db.execute(
            text(
                """
                SELECT 1 FROM handoff_tasks
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND trigger_reason LIKE :trigger_pattern
                  AND closed_at IS NULL
                LIMIT 1
                """
            ),
            {"cid": conversation_id, "trigger_pattern": f"{TRIGGER_PREFIX}%"},
        )
    ).fetchone()
    if existing:
        return True

    history_rows = (
        await db.execute(
            text(
                """
                SELECT sender_type, content
                FROM messages
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND COALESCE(content_type, 'text') = 'text'
                ORDER BY created_at DESC
                LIMIT 10
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchall()
    history = "\n".join(
        f"{str(row[0] or 'unknown')}: {str(row[1] or '')[:500]}"
        for row in reversed(history_rows)
    )
    classifier_input = "\n".join(part for part in (history, f"media_context: {media_context}" if media_context else "") if part)
    result = await chat(
        [
            {
                "role": "system",
                "content": (
                    "You classify purchase intent for an adult digital-content offer. "
                    "Judge only whether the user shows meaningful interest in selecting, receiving, "
                    "pricing, paying for, or learning more about photos, videos, VIP content, or a live call. "
                    "Greetings, emojis, unrelated chat, rejection, and silence are not interest. "
                    "Explicit rejection, refusal, stop requests, inability to pay, or negative wording always "
                    "means none, even when words such as video, photo, price, buy, VIP, or call are present. "
                    "Return strict JSON only: "
                    '{"level":"none|warm|hot","score":0,"reason":"short reason"}.'
                ),
            },
            {"role": "user", "content": classifier_input or effective_content},
        ],
        trace_id=f"{trace_id}-interest",
        temperature=0.0,
        max_tokens=50,
        purpose="aux",
    )
    parsed = _parse_json_object(result.content) if not result.error else None
    if parsed:
        level = str(parsed.get("level") or "none").strip().lower()
        try:
            score = max(0, min(100, int(float(parsed.get("score") or 0))))
        except (TypeError, ValueError):
            score = 0
        reason = str(parsed.get("reason") or "AI judged campaign interest").strip()[:240]
        interested = level in {"warm", "hot"} or score >= 60
    else:
        interested = bool(_POSITIVE_FALLBACK.search(effective_content)) and not bool(
            _NEGATIVE_INTENT.search(effective_content)
        )
        level = "warm" if interested else "none"
        score = 60 if interested else 0
        reason = "keyword fallback after classifier failure"

    if _CAMPAIGN_OPTION_INTENT.fullmatch(content):
        level, score, interested = "hot", 85, True
        reason = f"selected fixed campaign option {content.strip()[0]}"
    elif _PRICE_INTENT.search(content):
        level, score, interested = "warm", 65, True
        reason = "asked about price or fees"
    elif level == "hot":
        score = max(score, 80)
    elif level == "warm":
        score = max(score, 60)

    logger.bind(
        component="fixed_campaign_interest",
        trace_id=trace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        interest_level=level,
        interest_score=score,
        classifier_model=result.model_used,
        classifier_error=result.error,
    ).info("fixed_campaign_interest.classified")
    if not interested:
        return False

    trigger_reason = f"{TRIGGER_PREFIX}{level}:{score}"[:100]
    await db.execute(
        text(
            """
            INSERT INTO handoff_tasks (
              id, user_id, conversation_id, priority, trigger_reason, status,
              draft_content, draft_created_at, countdown_seconds, created_at
            )
            SELECT
              CAST(:id AS uuid), CAST(:uid AS uuid), CAST(:cid AS uuid),
              :priority, :trigger_reason, 'pending', :reason, NOW(), 0, NOW()
            WHERE NOT EXISTS (
              SELECT 1 FROM handoff_tasks
              WHERE conversation_id = CAST(:cid AS uuid)
                AND trigger_reason LIKE :trigger_pattern
                AND closed_at IS NULL
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "cid": conversation_id,
            "priority": "P1" if level == "hot" or score >= 80 else "P2",
            "trigger_reason": trigger_reason,
            "trigger_pattern": f"{TRIGGER_PREFIX}%",
            "reason": f"AI意向判断：{level} / {score}分；{reason}",
        },
    )
    return True
