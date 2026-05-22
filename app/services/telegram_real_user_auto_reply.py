"""MTProto real-user inbound auto-reply bridge."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.llm_orchestrator import LLMOrchestratorError, generate_reply

CONTEXT_MAX_MESSAGES = 20
CONTEXT_TTL_SECONDS = 86400 * 3


def _make_trace_id(message_id: str | None = None) -> str:
    suffix = message_id or uuid.uuid4().hex[:8]
    return f"tg-real-auto-{suffix}-{uuid.uuid4().hex[:10]}"


async def _push_context(redis: Any, conv_id: str, role: str, content: str, msg_id: str) -> None:
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


async def _get_or_create_user(db, *, channel: str, external_id: str) -> str:
    row = (
        await db.execute(
            text("SELECT id FROM users WHERE channel=:channel AND external_id=:external_id"),
            {"channel": channel, "external_id": external_id},
        )
    ).fetchone()
    if row:
        return str(row[0])

    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO users (id, channel, external_id, status)
            VALUES (:id, :channel, :external_id, 'active')
            """
        ),
        {"id": user_id, "channel": channel, "external_id": external_id},
    )
    await db.execute(
        text("INSERT INTO user_profiles (user_id, preferences) VALUES (:user_id, '{}'::jsonb) ON CONFLICT DO NOTHING"),
        {"user_id": user_id},
    )
    await db.commit()
    return user_id


async def _get_or_create_conversation(db, *, user_id: str, channel: str) -> str:
    row = (
        await db.execute(
            text(
                """
                SELECT id
                FROM conversations
                WHERE user_id=:user_id AND state NOT IN ('CLOSED','ESCALATED')
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
    ).fetchone()
    if row:
        return str(row[0])

    conv_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO conversations (id, user_id, channel, state, last_message_at)
            VALUES (:id, :user_id, :channel, 'AI_ACTIVE', NOW())
            """
        ),
        {"id": conv_id, "user_id": user_id, "channel": channel},
    )
    await db.commit()
    return conv_id


async def _persist_message(
    db,
    *,
    conversation_id: str,
    sender_type: str,
    sender_id: str,
    content: str,
) -> str:
    msg_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender_type, sender_id, content, content_type)
            VALUES (:id, :conversation_id, :sender_type, :sender_id, :content, 'text')
            """
        ),
        {
            "id": msg_id,
            "conversation_id": conversation_id,
            "sender_type": sender_type,
            "sender_id": sender_id,
            "content": content,
        },
    )
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"),
        {"id": conversation_id},
    )
    await db.commit()
    return msg_id


async def handle_mtproto_inbound_auto_reply(
    *,
    client: Any,
    raw_event: Any,
    redis: Any,
    account_id: str,
) -> None:
    """Enqueue MTProto inbound and send an AI reply through the same real-user client."""
    from services.mtproto.human_like_send import send_human_like_message
    from services.mtproto.newmessage_inbound import enqueue_new_message

    queue_id, envelope = await enqueue_new_message(redis, raw_event, account_id=account_id)
    message_id = envelope.metadata.telegram_message_id
    trace_id = envelope.trace_id or _make_trace_id(message_id)
    log = logger.bind(
        component="mtproto_auto_reply",
        trace_id=trace_id,
        account_id=account_id,
        external_user_id=envelope.external_user_id,
        queue_id=queue_id,
    )

    if queue_id is None:
        log.info("mtproto_auto_reply.duplicate_skip")
        return

    if envelope.message_type != "text" or not envelope.content.strip():
        log.info("mtproto_auto_reply.non_text_skip")
        return

    channel = "telegram_real_user"
    async with AsyncSessionLocal() as db:
        user_id = await _get_or_create_user(db, channel=channel, external_id=envelope.external_user_id)
        conv_id = await _get_or_create_conversation(db, user_id=user_id, channel=channel)
        inbound_msg_id = await _persist_message(
            db,
            conversation_id=conv_id,
            sender_type="user",
            sender_id=user_id,
            content=envelope.content,
        )
        try:
            await _push_context(redis, conv_id, "user", envelope.content, inbound_msg_id)
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning("mtproto_auto_reply.context_push_failed")

        try:
            reply_text = await generate_reply(
                user_id=user_id,
                conversation_id=conv_id,
                user_text=envelope.content,
                trace_id=trace_id,
                redis=redis,
                db=db,
                trigger_message_id=inbound_msg_id,
            )
        except LLMOrchestratorError as exc:
            log.bind(reason=str(exc)).warning("mtproto_auto_reply.orchestrator_failed")
            reply_text = "现在有点忙，稍后再聊好吗？"

        peer = getattr(raw_event, "chat_id", None) or envelope.metadata.telegram_chat_id or envelope.external_user_id[3:]
        sent = await send_human_like_message(client, int(peer), reply_text, sleep=asyncio.sleep)
        outbound_msg_id = await _persist_message(
            db,
            conversation_id=conv_id,
            sender_type="assistant",
            sender_id=account_id,
            content=reply_text,
        )
        try:
            await _push_context(redis, conv_id, "assistant", reply_text, outbound_msg_id)
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning("mtproto_auto_reply.reply_context_push_failed")

        log.bind(
            conversation_id=conv_id,
            inbound_msg_id=inbound_msg_id,
            outbound_msg_id=outbound_msg_id,
            telegram_message_id=getattr(sent, "id", None),
        ).info("mtproto_auto_reply.sent")
