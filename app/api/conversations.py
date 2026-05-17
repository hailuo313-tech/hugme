"""
Conversations API
- GET  /api/v1/conversations/{conv_id}        基本信息
- POST /api/v1/conversations/{conv_id}/reply  生成 AI 回复（D2-2.1：接入 LLM Orchestrator）
"""
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.messages import get_redis  # 复用 messages.py 已有的 Redis 单例
from core.database import get_db
from services.llm_orchestrator import (
    LLMOrchestratorError,
    generate_reply,
)
from services.reply_consistency import (
    evaluate_reply_consistency,
    load_reply_consistency_context,
)

router = APIRouter()


CONTEXT_MAX_MESSAGES = 20
CONTEXT_TTL_SECONDS = 86400 * 3


def _make_trace_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16]


async def _push_assistant_context(redis, conv_id: str, content: str, msg_id: str) -> None:
    """与 messages.py / telegram.py 同款 ctx 写入（assistant 角色）。"""
    entry = json.dumps(
        {
            "role": "assistant",
            "content": content,
            "msg_id": msg_id,
            "ts": int(time.time()),
        },
        ensure_ascii=False,
    )
    pipe = redis.pipeline()
    pipe.rpush(f"ctx:{conv_id}", entry)
    pipe.ltrim(f"ctx:{conv_id}", -CONTEXT_MAX_MESSAGES, -1)
    pipe.expire(f"ctx:{conv_id}", CONTEXT_TTL_SECONDS)
    await pipe.execute()


@router.get("/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM conversations WHERE id=:id"), {"id": conv_id}
    )
    conv = result.fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return dict(conv._mapping)


@router.post("/{conv_id}/reply")
async def ai_reply(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """对 ``conv_id`` 生成一条 AI 回复：

    1. 取该会话最近一条 ``sender_type='user'`` 的消息作为 ``user_text``。
    2. 调 ``llm_orchestrator.generate_reply``（带 Redis 短期上下文）。
    3. 持久化 ``assistant`` 消息（messages 表 + ctx）。
    4. 返回 ``{reply_content, message_id, trace_id, model_used*}``。

    HTTP 状态：
    - 200 成功
    - 404 conversation 不存在 / 没有可回复的 user 消息
    - 503 orchestrator 失败（LLMOrchestratorError）
    """
    trace_id = getattr(request.state, "trace_id", _make_trace_id())
    log = logger.bind(trace_id=trace_id, component="api.conversations", conv_id=conv_id)

    conv_row = (
        await db.execute(
            text("SELECT id, user_id FROM conversations WHERE id=:id"),
            {"id": conv_id},
        )
    ).fetchone()
    if not conv_row:
        log.warning("conversation.reply.not_found")
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = str(conv_row[1])

    last_user = (
        await db.execute(
            text(
                "SELECT id, content FROM messages "
                "WHERE conversation_id=:cid AND sender_type='user' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"cid": conv_id},
        )
    ).fetchone()
    if not last_user or not last_user[1]:
        log.warning("conversation.reply.no_user_message")
        raise HTTPException(
            status_code=404,
            detail="No user message found in this conversation",
        )

    trigger_msg_id = str(last_user[0])
    user_text = str(last_user[1])

    redis = await get_redis()

    try:
        reply_text = await generate_reply(
            user_id=user_id,
            conversation_id=conv_id,
            user_text=user_text,
            trace_id=trace_id,
            redis=redis,
            db=db,
            trigger_message_id=trigger_msg_id,
        )
    except LLMOrchestratorError as exc:
        log.bind(result="failed", reason=str(exc)).warning(
            "conversation.reply.orchestrator_failed"
        )
        raise HTTPException(
            status_code=503,
            detail="LLM orchestrator unavailable",
        )

    try:
        ctx = await load_reply_consistency_context(db, conv_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "conversation.reply.consistency_context_failed"
        )
        ctx = {}
    consistency = evaluate_reply_consistency(
        reply_text=reply_text,
        character=ctx.get("character"),
    )
    reply_text = consistency.output_text
    log.bind(**consistency.as_log_dict()).info("conversation.reply.consistency_checked")

    bot_msg_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO messages "
            "(id,conversation_id,sender_type,sender_id,content,content_type,"
            " consistency_score) "
            "VALUES (:id,:cid,'assistant','bot',:ct,'text', :cs)"
        ),
        {
            "id": bot_msg_id,
            "cid": conv_id,
            "ct": reply_text,
            "cs": consistency.score,
        },
    )
    await db.execute(
        text("UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"),
        {"id": conv_id},
    )
    await db.commit()

    try:
        await _push_assistant_context(redis, conv_id, reply_text, bot_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning(
            "conversation.reply.ctx_push_failed"
        )

    log.bind(result="success", message_id=bot_msg_id).info("conversation.reply.complete")

    return {
        "reply_content": reply_text,
        "message_id": bot_msg_id,
        "trace_id": trace_id,
    }
