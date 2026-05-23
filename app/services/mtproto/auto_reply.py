"""Runtime MTProto inbound handler that reads, thinks, and replies."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.llm_orchestrator import LLMOrchestratorError, generate_reply
from services.mtproto.human_like_send import HumanLikeSendPolicy, send_human_like_message


CONTEXT_MAX_MESSAGES = 50
CONTEXT_TTL_SECONDS = 86400 * 3

_redis_client = None

MTProtoReplyPolicy = HumanLikeSendPolicy(
    short_text_seconds=3.0,
    medium_text_seconds=6.0,
    long_text_seconds=10.0,
    very_long_text_seconds=15.0,
    minimum_typing_seconds=3.0,
    minimum_inter_message_seconds=0.0,
    typing_start_delay_seconds=5.0,
)


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


def _trace_id(message_id: str | None) -> str:
    suffix = message_id or uuid.uuid4().hex[:8]
    return f"mtproto-{suffix}-{uuid.uuid4().hex[:10]}"


def _reply_delay_policy(reply_text: str) -> HumanLikeSendPolicy:
    size = len(reply_text or "")
    if size <= 10:
        delay = 3.0
    elif size <= 30:
        delay = 6.0
    elif size <= 50:
        delay = 10.0
    elif size <= 100:
        delay = 15.0
    elif size <= 200:
        delay = 25.0
    else:
        delay = 30.0
    return HumanLikeSendPolicy(
        short_text_seconds=delay,
        medium_text_seconds=delay,
        long_text_seconds=delay,
        very_long_text_seconds=delay,
        minimum_typing_seconds=delay,
        minimum_inter_message_seconds=0.0,
        typing_start_delay_seconds=5.0,
    )


async def _push_context(redis, conv_id: str, role: str, content: str, msg_id: str) -> None:
    key = f"ctx:{conv_id}"
    entry = json.dumps(
        {"role": role, "content": content, "msg_id": msg_id, "ts": int(time.time())},
        ensure_ascii=False,
    )
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -CONTEXT_MAX_MESSAGES, -1)
    pipe.expire(key, CONTEXT_TTL_SECONDS)
    await pipe.execute()


async def _get_or_create_user_and_conversation(
    *,
    external_id: str,
    nickname: str | None,
) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        user_row = (
            await db.execute(
                text(
                    "INSERT INTO users "
                    "(channel, external_id, nickname, age_verified, status, created_at, updated_at) "
                    "VALUES ('telegram_real_user', :external_id, :nickname, true, 'active', NOW(), NOW()) "
                    "ON CONFLICT (channel, external_id) DO UPDATE SET updated_at=NOW() "
                    "RETURNING id"
                ),
                {"external_id": external_id, "nickname": nickname},
            )
        ).fetchone()
        user_id = str(user_row[0])

        await db.execute(
            text(
                "INSERT INTO user_profiles "
                "(user_id, preferences, chat_style, user_level, chat_route, updated_at) "
                "VALUES (:uid, CAST(:prefs AS jsonb), 'casual', 'C', 'ai_auto', NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "preferences = user_profiles.preferences || CAST(:prefs AS jsonb), "
                "updated_at=NOW()"
            ),
            {
                "uid": user_id,
                "prefs": json.dumps({"onboarding_step": 6}, ensure_ascii=False),
            },
        )

        conv_row = (
            await db.execute(
                text(
                    "SELECT id FROM conversations "
                    "WHERE user_id=:uid AND state NOT IN ('CLOSED','ESCALATED') "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
        ).fetchone()
        if conv_row:
            conv_id = str(conv_row[0])
        else:
            conv_id = str(uuid.uuid4())
            await db.execute(
                text(
                    "INSERT INTO conversations (id, user_id, channel, state, created_at, updated_at) "
                    "VALUES (:cid, :uid, 'telegram_real_user', 'AI_ACTIVE', NOW(), NOW())"
                ),
                {"cid": conv_id, "uid": user_id},
            )

        await db.commit()
        return user_id, conv_id


async def _persist_message(
    *,
    conv_id: str,
    sender_type: str,
    sender_id: str,
    content: str,
    model_name: str | None = None,
) -> str:
    msg_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sender_type, sender_id, content, content_type, model_name, created_at) "
                "VALUES (:id, :cid, :sender_type, :sender_id, :content, 'text', :model_name, NOW())"
            ),
            {
                "id": msg_id,
                "cid": conv_id,
                "sender_type": sender_type,
                "sender_id": sender_id,
                "content": content,
                "model_name": model_name,
            },
        )
        await db.execute(
            text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:cid"),
            {"cid": conv_id},
        )
        await db.commit()
    return msg_id


async def handle_mtproto_new_message(client: Any, account_id: uuid.UUID, event: Any) -> None:
    """Handle one incoming real-user Telegram message end to end."""
    message = getattr(event, "message", event)
    if getattr(message, "out", False):
        return

    text_value = (
        getattr(message, "raw_text", None)
        or getattr(message, "text", None)
        or getattr(message, "message", None)
        or ""
    ).strip()
    if not text_value:
        logger.info("mtproto.inbound.skip_empty")
        return

    sender = await event.get_sender() if hasattr(event, "get_sender") else None
    sender_id = str(
        getattr(message, "sender_id", None)
        or getattr(event, "sender_id", None)
        or getattr(sender, "id", "")
    )
    if not sender_id:
        logger.warning("mtproto.inbound.missing_sender")
        return

    message_id = str(getattr(message, "id", "") or getattr(event, "id", "") or "")
    trace_id = _trace_id(message_id)
    external_id = f"tg_{sender_id}"
    nickname = getattr(sender, "first_name", None) or getattr(sender, "username", None)
    log = logger.bind(trace_id=trace_id, account_id=str(account_id), external_id=external_id)

    try:
        await client.send_read_acknowledge(getattr(event, "chat_id", None), message=message)
        log.info("mtproto.inbound.mark_read")
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.inbound.mark_read_failed")

    user_id, conv_id = await _get_or_create_user_and_conversation(
        external_id=external_id,
        nickname=nickname,
    )
    log = log.bind(user_id=user_id, conv_id=conv_id, telegram_message_id=message_id)

    user_msg_id = await _persist_message(
        conv_id=conv_id,
        sender_type="user",
        sender_id=user_id,
        content=text_value,
    )
    log.bind(message_id=user_msg_id).info("mtproto.inbound.persisted")

    redis = await _get_redis()
    try:
        await _push_context(redis, conv_id, "user", text_value, user_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.context.push_failed")

    async with AsyncSessionLocal() as db:
        try:
            reply_text = await generate_reply(
                user_id=user_id,
                conversation_id=conv_id,
                user_text=text_value,
                trace_id=trace_id,
                redis=redis,
                db=db,
                trigger_message_id=user_msg_id,
            )
        except LLMOrchestratorError as exc:
            log.bind(reason=str(exc)).warning("mtproto.orchestrator.failed")
            reply_text = "I am a little busy right now, talk in a bit?"

    peer = getattr(event, "chat_id", None) or sender_id
    sent = await send_human_like_message(
        client,
        peer,
        reply_text,
        policy=_reply_delay_policy(reply_text),
    )
    sent_id = str(getattr(sent, "id", "") or "")
    assistant_msg_id = await _persist_message(
        conv_id=conv_id,
        sender_type="assistant",
        sender_id=str(account_id),
        content=reply_text,
        model_name=getattr(settings, "OPENROUTER_MODEL", None),
    )
    try:
        await _push_context(redis, conv_id, "assistant", reply_text, assistant_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("mtproto.reply.ctx_push_failed")
    log.bind(message_id=assistant_msg_id, telegram_sent_id=sent_id).info("mtproto.reply.sent")
