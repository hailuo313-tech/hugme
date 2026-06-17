"""Nurture reply: spam filter, intent classification, and inbound-call guidance."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.product_i18n import (
    NURTURE_ACCEPT_ACK_COPY,
    NURTURE_DELAY_FOLLOWUP_COPY,
    NURTURE_NEED_HELP_COPY,
    pick_localized,
)
_SPAM_URL_RE = re.compile(
    r"(https?://|t\.me/|telegram\.me/|@\w{4,})",
    re.IGNORECASE,
)
_MULTI_URL_RE = re.compile(r"https?://|t\.me/|telegram\.me/", re.IGNORECASE)
_TME_FULL_URL_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/[^\s]+",
    re.IGNORECASE,
)

_ACCEPT_RE = re.compile(
    r"(^|\b)(yes|yeah|yep|yup|ok|okay|sure|call me|video call|facetime|"
    r"let'?s do it|go ahead|"
    r"好|可以|行|来吧|打给我|视频|"
    r"sí|si|claro|vale|llamada|videollamada|"
    r"sim|quero|pode|chamada|vídeo|video)\b",
    re.IGNORECASE | re.UNICODE,
)
_DELAY_RE = re.compile(
    r"(tomorrow|later|tonight|busy|wait|"
    r"明天|等会|稍后|忙|"
    r"mañana|después|ocupad|"
    r"amanhã|depois|ocupad)",
    re.IGNORECASE | re.UNICODE,
)
_NEED_HELP_RE = re.compile(
    r"(how|what is|not sure|don'?t know|where|"
    r"怎么|如何|不会|"
    r"cómo|como|no sé|"
    r"como|não sei)",
    re.IGNORECASE | re.UNICODE,
)
_NEGATIVE_RE = re.compile(
    r"(^|\b)(no|nope|stop|not interested|don'?t|leave me|"
    r"不要|别烦|滚|"
    r"no gracias|para|"
    r"não|pare)\b",
    re.IGNORECASE | re.UNICODE,
)
# User asks the bot to initiate an outbound call — not accepting a nurture invite.
_OUTBOUND_CALL_REQUEST_RE = re.compile(
    r"(?:"
    r"\bcan you (?:call|video|facetime|initiate)\b|"
    r"\bcould you (?:call|video|facetime)\b|"
    r"\bwill you call\b|"
    r"\byou call me\b|"
    r"\bpuedes (?:llamar|hacer|iniciar)\b|"
    r"\bme puedes (?:llamar|hacer)\b|"
    r"\bhazme (?:una )?(?:llamada|videollamada)\b|"
    r"\biniciar (?:una )?videollamada\b|"
    r"\bme llamas\b|"
    r"\bvocê pode (?:ligar|chamar|fazer)\b|"
    r"\bvoce pode (?:ligar|chamar|fazer)\b|"
    r"\bpode me ligar\b|"
    r"\?[^.!?]{0,40}\bvideollamada\b|"
    r"\?[^.!?]{0,40}\bvideo call\b"
    r")",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True)
class NurtureReplyAction:
    intent: str
    valid_reply: bool
    immediate_reply_text: str | None = None
    trigger_outbound_call: bool = False
    cancel_pending_nurture: bool = False
    nurture_language: str | None = None
    matched_schedule_id: str | None = None


def _strip_telegram_urls(text_value: str) -> str:
    """Remove Telegram URLs/handles before measuring non-link spam content."""
    cleaned = _TME_FULL_URL_RE.sub(" ", text_value)
    cleaned = re.sub(r"@\w{4,}", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_spam_reply(text_value: str | None) -> bool:
    text_value = str(text_value or "").strip()
    if not text_value:
        return False
    url_hits = len(_MULTI_URL_RE.findall(text_value))
    if url_hits >= 2:
        return True
    stripped = _strip_telegram_urls(text_value)
    if _SPAM_URL_RE.search(text_value) and len(text_value) > 40:
        if len(stripped) < 20:
            return True
    if _TME_FULL_URL_RE.search(text_value) and len(stripped) < 20:
        return True
    if text_value.count("http") >= 2 or text_value.count("t.me/") >= 2:
        return True
    return False


def classify_nurture_reply_intent(text_value: str | None, *, language: str = "en") -> str:
    text_value = str(text_value or "").strip()
    if not text_value:
        return "empty"
    if is_spam_reply(text_value):
        return "spam"
    if _NEGATIVE_RE.search(text_value):
        return "negative"
    if _NEED_HELP_RE.search(text_value):
        return "need_help"
    if _OUTBOUND_CALL_REQUEST_RE.search(text_value):
        return "open_chat"
    if _ACCEPT_RE.search(text_value):
        return "accept_call"
    if _DELAY_RE.search(text_value):
        return "delay"
    return "open_chat"


async def handle_nurture_user_reply(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int,
    account_id: str,
    user_text: str,
    trace_id: str | None,
    telegram_access_hash: int | None = None,
) -> NurtureReplyAction:
    from services.app_download_nurture import (
        detect_nurture_language_from_text,
        persist_user_nurture_language,
    )

    lang = detect_nurture_language_from_text(user_text)
    await persist_user_nurture_language(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        language=lang,
    )

    intent = classify_nurture_reply_intent(user_text, language=lang)
    valid = intent not in {"spam", "empty"}

    schedule = await _latest_sent_nurture_for_conversation(db, conversation_id=conversation_id)
    schedule_id = str(schedule["id"]) if schedule else None

    if schedule_id:
        await _record_reply_on_schedule(
            db,
            schedule_id=schedule_id,
            intent=intent,
            valid_reply=valid,
            user_text=user_text,
        )

    log = logger.bind(
        component="nurture_reply_handler",
        trace_id=trace_id,
        conversation_id=conversation_id,
        intent=intent,
        valid_reply=valid,
        nurture_language=lang,
    )

    if intent == "spam":
        log.info("nurture_reply.spam_ignored")
        return NurtureReplyAction(
            intent=intent,
            valid_reply=False,
            nurture_language=lang,
            matched_schedule_id=schedule_id,
        )

    if intent == "accept_call":
        await _cancel_pending_nurture_rounds(
            db,
            conversation_id=conversation_id,
            sender_account_id=account_id,
            reason="accepted_inbound_video_call",
        )
        log.info("nurture_reply.accept_call_inbound_guided")
        return NurtureReplyAction(
            intent=intent,
            valid_reply=True,
            immediate_reply_text=pick_localized(NURTURE_ACCEPT_ACK_COPY, lang),
            cancel_pending_nurture=True,
            nurture_language=lang,
            matched_schedule_id=schedule_id,
        )

    if intent == "need_help":
        log.info("nurture_reply.need_help")
        return NurtureReplyAction(
            intent=intent,
            valid_reply=True,
            immediate_reply_text=pick_localized(NURTURE_NEED_HELP_COPY, lang),
            nurture_language=lang,
            matched_schedule_id=schedule_id,
        )

    if intent == "delay":
        await _schedule_delay_followup(
            db,
            user_id=user_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            chat_id=chat_id,
            account_id=account_id,
            language=lang,
            trace_id=trace_id,
        )
        log.info("nurture_reply.delay_scheduled")
        return NurtureReplyAction(
            intent=intent,
            valid_reply=True,
            nurture_language=lang,
            matched_schedule_id=schedule_id,
        )

    if intent == "negative":
        await _cancel_pending_nurture_rounds(
            db,
            conversation_id=conversation_id,
            sender_account_id=account_id,
            reason="user_negative",
        )
        log.info("nurture_reply.negative_cancel")
        return NurtureReplyAction(
            intent=intent,
            valid_reply=True,
            cancel_pending_nurture=True,
            nurture_language=lang,
            matched_schedule_id=schedule_id,
        )

    if valid and schedule_id:
        await _cancel_pending_nurture_rounds(
            db,
            conversation_id=conversation_id,
            sender_account_id=account_id,
            reason="valid_user_reply",
        )

    log.info("nurture_reply.open_chat")
    return NurtureReplyAction(
        intent=intent,
        valid_reply=valid,
        nurture_language=lang,
        matched_schedule_id=schedule_id,
    )


async def _latest_sent_nurture_for_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id, sent_at, metadata
                FROM message_schedules
                WHERE metadata->>'delivery_mode' = 'app_download_nurture'
                  AND metadata->>'conversation_id' = :conversation_id
                  AND status = 'sent'
                  AND metadata->>'nurture_kind' = 'video_chat'
                ORDER BY sent_at DESC
                LIMIT 1
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _record_reply_on_schedule(
    db: AsyncSession,
    *,
    schedule_id: str,
    intent: str,
    valid_reply: bool,
    user_text: str,
) -> None:
    await db.execute(
        text(
            """
            UPDATE message_schedules
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:schedule_id AS uuid)
            """
        ),
        {
            "schedule_id": schedule_id,
            "patch": json.dumps(
                {
                    "nurture_reply_intent": intent,
                    "nurture_valid_reply": valid_reply,
                    "nurture_raw_reply": True,
                    "nurture_reply_preview": str(user_text or "")[:200],
                    "nurture_replied_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
        },
    )


async def _cancel_pending_nurture_rounds(
    db: AsyncSession,
    *,
    conversation_id: str,
    sender_account_id: str,
    reason: str,
) -> None:
    await db.execute(
        text(
            """
            UPDATE message_schedules
            SET status = 'failed',
                failure_reason = :reason,
                updated_at = NOW()
            WHERE metadata->>'delivery_mode' = 'app_download_nurture'
              AND metadata->>'conversation_id' = :conversation_id
              AND COALESCE(metadata->>'sender_account_id', '') = COALESCE(:sender_account_id, '')
              AND metadata->>'trigger' = ANY(:triggers)
              AND status = 'pending'
            """
        ),
        {
            "conversation_id": conversation_id,
            "sender_account_id": sender_account_id,
            "reason": reason,
            "triggers": ["nurture_round_1", "nurture_round_2", "nurture_round_3"],
        },
    )


async def _schedule_delay_followup(
    db: AsyncSession,
    *,
    user_id: str,
    external_user_id: str,
    conversation_id: str,
    chat_id: int,
    account_id: str,
    language: str,
    trace_id: str | None,
) -> None:
    from services.app_download_nurture import (
        APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
        user_nurture_cycle_completed,
    )

    if await user_nurture_cycle_completed(db, user_id=user_id):
        logger.bind(
            component="nurture_reply_handler",
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=user_id,
        ).info("nurture_reply.delay_skip_cycle_completed")
        return

    send_at = datetime.now(timezone.utc) + timedelta(hours=4)
    rule_key = f"nurture_delay:{conversation_id}:{int(send_at.timestamp())}"
    content = pick_localized(NURTURE_DELAY_FOLLOWUP_COPY, language)
    metadata = {
        "delivery_mode": APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
        "trigger": "nurture_delay_followup",
        "conversation_id": conversation_id,
        "rule_key": rule_key,
        "sender_account_id": account_id,
        "language": language,
        "nurture_kind": "video_chat",
    }
    await db.execute(
        text(
            """
            INSERT INTO message_schedules (
                user_id, external_user_id, message_type, content, platform, chat_id,
                account_id, status, send_at, priority, metadata, trace_id
            ) VALUES (
                CAST(:user_id AS uuid), :external_user_id, 'app_download_followup', :content,
                'telegram_real_user', :chat_id, CAST(:account_id AS uuid), 'pending', :send_at,
                70, CAST(:metadata AS jsonb), :trace_id
            )
            """
        ),
        {
            "user_id": user_id,
            "external_user_id": external_user_id,
            "content": content,
            "chat_id": chat_id,
            "account_id": account_id,
            "send_at": send_at,
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "trace_id": trace_id,
        },
    )
