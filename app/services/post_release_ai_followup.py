"""Post-release AI follow-up checks for operator-released conversations."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.emotion_lexicon import detect_language_from_text, normalize_language
from services.llm import chat as llm_chat
from services.llm_orchestrator import LLMOrchestratorError, generate_reply
from services.ai_message_limit import AIMessageLimitReached
from services.reply_sanitize import sanitize_outbound_reply
from services.telegram_send import telegram_chat_id_from_external


DELIVERY_MODE = "post_release_ai_followup"
MESSAGE_TYPE = "post_release_ai_followup"
PLACEHOLDER_CONTENT = "__post_release_ai_followup__"
CHECK_OFFSETS_MINUTES = (10, 30, 60, 120)
FOLLOWUP_WINDOW = timedelta(hours=2, minutes=5)


@dataclass(frozen=True)
class PreparedPostReleaseFollowup:
    should_send: bool
    content: str = ""
    reason: str = ""
    metadata: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _compact_preview(value: str | None, *, limit: int = 160) -> str:
    text_value = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "..."


async def schedule_post_release_ai_checks(
    db: AsyncSession,
    *,
    conversation_id: str,
    source: str,
    operator_id: str | None = None,
    trace_id: str | None = None,
) -> int:
    """Queue several lightweight checks after a conversation is released to AI."""
    row = (
        await db.execute(
            text(
                """
                SELECT
                  c.id::text AS conversation_id,
                  c.user_id::text AS user_id,
                  COALESCE(NULLIF(c.channel, ''), NULLIF(u.channel, ''), 'telegram_real_user') AS platform,
                  u.external_id,
                  COALESCE(
                    (
                      SELECT m.sender_id
                      FROM messages m
                      JOIN telegram_accounts ta ON ta.id::text = m.sender_id
                      WHERE m.conversation_id = c.id
                        AND m.sender_type = 'assistant'
                      ORDER BY m.created_at DESC
                      LIMIT 1
                    ),
                    (
                      SELECT t.account_id::text
                      FROM telegram_peer_cache t
                      WHERE t.conversation_id = c.id
                      ORDER BY t.last_seen_at DESC
                      LIMIT 1
                    )
                  ) AS telegram_account_id,
                  (
                    SELECT t.access_hash
                    FROM telegram_peer_cache t
                    WHERE t.conversation_id = c.id
                    ORDER BY
                      CASE WHEN t.access_hash IS NOT NULL THEN 0 ELSE 1 END,
                      t.last_seen_at DESC
                    LIMIT 1
                  ) AS telegram_access_hash
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                  AND u.status = 'active'
                """
            ),
            {"cid": conversation_id},
        )
    ).mappings().first()
    if not row:
        return 0

    external_user_id = str(row.get("external_id") or "")
    chat_id = telegram_chat_id_from_external(external_user_id)
    if chat_id is None:
        logger.bind(conversation_id=conversation_id).warning(
            "post_release_ai_followup.schedule.missing_chat_id"
        )
        return 0

    duplicate = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM message_schedules
                WHERE metadata->>'delivery_mode' = :delivery_mode
                  AND metadata->>'conversation_id' = :conversation_id
                  AND created_at >= NOW() - INTERVAL '2 hours'
                  AND status IN ('pending', 'sending', 'sent')
                LIMIT 1
                """
            ),
            {
                "delivery_mode": DELIVERY_MODE,
                "conversation_id": conversation_id,
            },
        )
    ).fetchone()
    if duplicate:
        return 0

    release_at = _utc_now()
    release_batch_id = str(uuid.uuid4())
    account_id = str(row.get("telegram_account_id") or "").strip() or None
    access_hash = _safe_int(row.get("telegram_access_hash"))
    queued = 0
    for offset in CHECK_OFFSETS_MINUTES:
        metadata = {
            "delivery_mode": DELIVERY_MODE,
            "conversation_id": conversation_id,
            "release_source": source,
            "operator_id": operator_id,
            "release_batch_id": release_batch_id,
            "release_at": release_at.isoformat(),
            "check_offset_minutes": offset,
            "sender_account_id": account_id,
            "trace_id": trace_id,
        }
        if access_hash is not None:
            metadata["telegram_access_hash"] = str(access_hash)

        await db.execute(
            text(
                """
                INSERT INTO message_schedules (
                    user_id, external_user_id, message_type, content, platform, chat_id,
                    account_id, status, send_at, priority, metadata, trace_id
                )
                VALUES (
                    :user_id, :external_user_id, :message_type, :content,
                    :platform, :chat_id, :account_id, 'pending', :send_at,
                    :priority, CAST(:metadata AS jsonb), :trace_id
                )
                """
            ),
            {
                "user_id": str(row["user_id"]),
                "external_user_id": external_user_id,
                "message_type": MESSAGE_TYPE,
                "content": PLACEHOLDER_CONTENT,
                "platform": str(row.get("platform") or "telegram_real_user"),
                "chat_id": chat_id,
                "account_id": account_id,
                "send_at": release_at + timedelta(minutes=offset),
                "priority": 115,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "trace_id": trace_id,
            },
        )
        queued += 1

    logger.bind(
        conversation_id=conversation_id,
        source=source,
        release_batch_id=release_batch_id,
        queued=queued,
    ).info("post_release_ai_followup.scheduled")
    return queued


async def _load_followup_state(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT
                  c.state,
                  c.user_id::text AS user_id,
                  u.external_id,
                  COALESCE(NULLIF(c.channel, ''), NULLIF(u.channel, ''), 'telegram_real_user') AS platform,
                  (
                    SELECT m.id::text
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_user_message_id,
                  (
                    SELECT m.content
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_user_text,
                  (
                    SELECT m.created_at
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.sender_type = 'user'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_user_at,
                  (
                    SELECT m.created_at
                    FROM messages m
                    WHERE m.conversation_id = c.id
                      AND (
                        m.sender_type IN ('assistant', 'operator', 'system')
                        OR COALESCE(m.is_operator_message, false) = true
                      )
                    ORDER BY m.created_at DESC
                    LIMIT 1
                  ) AS last_outgoing_at,
                  (
                    SELECT MAX(ms.sent_at)
                    FROM message_schedules ms
                    WHERE ms.metadata->>'delivery_mode' = :delivery_mode
                      AND ms.metadata->>'conversation_id' = c.id::text
                      AND ms.status = 'sent'
                  ) AS last_followup_sent_at
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conversation_id, "delivery_mode": DELIVERY_MODE},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _load_recent_messages(
    db: AsyncSession,
    *,
    conversation_id: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT sender_type, content, created_at
                FROM messages
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND COALESCE(content, '') <> ''
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"cid": conversation_id, "limit": max(1, limit)},
        )
    ).mappings().all()
    return [dict(row) for row in reversed(rows)]


def _history_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in messages:
        role = str(row.get("sender_type") or "unknown")
        content = _compact_preview(str(row.get("content") or ""), limit=220)
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines[-12:])


async def _generate_contextual_checkin(
    db: AsyncSession,
    *,
    conversation_id: str,
    trace_id: str,
) -> str:
    history = await _load_recent_messages(db, conversation_id=conversation_id)
    context = _history_text(history)
    recent_user_text = " ".join(
        str(row.get("content") or "")
        for row in history
        if str(row.get("sender_type") or "").lower() == "user"
    )
    language = normalize_language(
        detect_language_from_text(recent_user_text or context, default="en"),
        default="en",
    )
    prompt = [
        {
            "role": "system",
            "content": (
                "Write one short natural follow-up message for this chat. "
                "Use the same language as the user. Refer to the recent context when useful. "
                "Do not mention operators, systems, checks, rules, or that this is a follow-up. "
                "Return only the message."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Detected language: {language}\n"
                f"Recent conversation:\n{context or '(no recent messages)'}\n\n"
                "Write one warm message to restart the conversation."
            ),
        },
    ]
    result = await llm_chat(
        messages=prompt,
        trace_id=trace_id,
        purpose="chat",
        temperature=0.72,
        max_tokens=90,
    )
    content = result.content if not result.error else ""
    return sanitize_outbound_reply(
        content or "Hey, I’m still here. What are you up to now?",
        max_sentences=1,
        max_chars=120,
        user_text=recent_user_text or context,
    )


async def prepare_post_release_followup_for_send(
    db: AsyncSession,
    *,
    message: dict[str, Any],
    trace_id: str,
) -> PreparedPostReleaseFollowup:
    metadata = message.get("metadata") or {}
    conversation_id = str(metadata.get("conversation_id") or "").strip()
    if not conversation_id:
        return PreparedPostReleaseFollowup(False, reason="missing_conversation_id")

    release_at = _parse_datetime(metadata.get("release_at")) or _utc_now()
    if _utc_now() - release_at > FOLLOWUP_WINDOW:
        return PreparedPostReleaseFollowup(False, reason="release_window_expired")

    state = await _load_followup_state(db, conversation_id=conversation_id)
    if not state:
        return PreparedPostReleaseFollowup(False, reason="conversation_missing")
    if str(state.get("state") or "") != "AI_ACTIVE":
        return PreparedPostReleaseFollowup(False, reason="conversation_not_ai_active")

    last_user_at = _parse_datetime(state.get("last_user_at"))
    last_outgoing_at = _parse_datetime(state.get("last_outgoing_at"))
    last_followup_sent_at = _parse_datetime(state.get("last_followup_sent_at"))
    has_unreplied_user = bool(
        last_user_at and (last_outgoing_at is None or last_user_at > last_outgoing_at)
    )

    reason = "unreplied_user_message" if has_unreplied_user else "warm_checkin"
    generated_for_message_id = state.get("last_user_message_id")
    user_text = str(state.get("last_user_text") or "").strip()

    if not has_unreplied_user:
        if last_followup_sent_at and last_followup_sent_at >= release_at:
            return PreparedPostReleaseFollowup(False, reason="already_checked_after_release")
        if last_outgoing_at and last_outgoing_at >= release_at:
            return PreparedPostReleaseFollowup(False, reason="already_outgoing_after_release")
        content = await _generate_contextual_checkin(
            db,
            conversation_id=conversation_id,
            trace_id=trace_id,
        )
    else:
        try:
            from core.redis import get_redis

            redis = await get_redis()
        except Exception:
            redis = None
        try:
            content = await generate_reply(
                user_id=str(state["user_id"]),
                conversation_id=conversation_id,
                user_text=user_text,
                trace_id=trace_id,
                redis=redis,
                db=db,
                trigger_message_id=str(generated_for_message_id)
                if generated_for_message_id
                else None,
            )
        except AIMessageLimitReached as exc:
            logger.bind(
                conversation_id=conversation_id,
                reason=str(exc),
            ).info("post_release_ai_followup.ai_limit")
            return PreparedPostReleaseFollowup(False, reason="ai_message_limit")
        except LLMOrchestratorError as exc:
            logger.bind(
                conversation_id=conversation_id,
                error_type=type(exc).__name__,
            ).warning("post_release_ai_followup.generate_reply_failed")
            return PreparedPostReleaseFollowup(False, reason="generate_reply_failed")

    content = sanitize_outbound_reply(content, user_text=user_text or None)
    if not content:
        return PreparedPostReleaseFollowup(False, reason="empty_content")

    return PreparedPostReleaseFollowup(
        True,
        content=content,
        reason=reason,
        metadata={
            "followup_reason": reason,
            "last_user_message_id": generated_for_message_id,
            "last_user_preview": _compact_preview(user_text),
            "last_user_at": last_user_at.isoformat() if last_user_at else None,
            "last_outgoing_at": last_outgoing_at.isoformat() if last_outgoing_at else None,
        },
    )


async def mark_post_release_followup_result(
    db: AsyncSession,
    *,
    message_id: str,
    result: PreparedPostReleaseFollowup,
) -> None:
    payload = {
        "post_release_check_result": {
            "should_send": result.should_send,
            "reason": result.reason,
            **(result.metadata or {}),
        }
    }
    await db.execute(
        text(
            """
            UPDATE message_schedules
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:payload AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": message_id, "payload": json.dumps(payload, ensure_ascii=False)},
    )
    await db.commit()


async def persist_post_release_followup_message(
    db: AsyncSession,
    *,
    message: dict[str, Any],
    content: str,
    sender_id: str,
) -> str | None:
    metadata = message.get("metadata") or {}
    conversation_id = metadata.get("conversation_id")
    if not conversation_id:
        return None
    row = (
        await db.execute(
            text(
                """
                INSERT INTO messages (
                    conversation_id, sender_type, sender_id, content, content_type,
                    model_name, created_at
                )
                VALUES (
                    CAST(:conversation_id AS uuid), 'assistant', :sender_id, :content,
                    'text', :model_name, NOW()
                )
                RETURNING id
                """
            ),
            {
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "content": content,
                "model_name": MESSAGE_TYPE,
            },
        )
    ).fetchone()
    await db.execute(
        text(
            """
            UPDATE conversations
            SET last_message_at=NOW(), updated_at=NOW()
            WHERE id=CAST(:cid AS uuid)
            """
        ),
        {"cid": conversation_id},
    )
    await db.commit()
    return str(row[0]) if row else None


def is_post_release_ai_followup_message(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata") or {}
    return (
        message.get("message_type") == MESSAGE_TYPE
        or metadata.get("delivery_mode") == DELIVERY_MODE
    )
