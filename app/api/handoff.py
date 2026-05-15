
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.admin import require_operator
from api.messages import get_redis
from core.database import get_db
from services.telegram_send import send_telegram_text, telegram_chat_id_from_external

router = APIRouter()

CONTEXT_MAX_MESSAGES = 20
CONTEXT_TTL_SECONDS = 86400 * 3


class ReplyData(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    used_script_id: Optional[str] = None


class ReturnAIData(BaseModel):
    notes: Optional[str] = None
    allow_upsell: bool = True


async def _push_operator_context(redis, conv_id: str, content: str, msg_id: str) -> None:
    entry = json.dumps(
        {
            "role": "assistant",
            "content": content,
            "msg_id": msg_id,
            "ts": int(time.time()),
            "operator": True,
        },
        ensure_ascii=False,
    )
    key = f"ctx:{conv_id}"
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -CONTEXT_MAX_MESSAGES, -1)
    pipe.expire(key, CONTEXT_TTL_SECONDS)
    await pipe.execute()


@router.post("/{task_id}/lock")
async def lock_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await db.execute(
        text(
            "UPDATE handoff_tasks SET status='HUMAN_LOCKED', locked_at=NOW() "
            "WHERE id=:id"
        ),
        {"id": task_id},
    )
    await db.commit()
    return {"status": "locked", "task_id": task_id}


@router.post(
    "/{task_id}/reply",
    summary="V001-P0-1：运营回复写入 messages 并经 Telegram 发给用户",
)
async def operator_reply(
    task_id: str,
    data: ReplyData,
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: dict = Depends(require_operator),
):
    try:
        uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="task_id must be a valid UUID")

    row = (
        await db.execute(
            text(
                """
                SELECT
                  ht.id AS task_id,
                  ht.conversation_id,
                  ht.status AS task_status,
                  u.id AS user_id,
                  u.channel,
                  u.external_id
                FROM handoff_tasks ht
                JOIN users u ON u.id = ht.user_id
                WHERE ht.id = :tid
                """
            ),
            {"tid": task_id},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="handoff task not found")

    mapping = dict(row._mapping)
    conv_id = str(mapping["conversation_id"])
    channel = mapping.get("channel")
    external_id = mapping.get("external_id")
    operator_id = str(payload.get("sub", ""))

    if channel != "telegram":
        raise HTTPException(
            status_code=400,
            detail=f"handoff reply not supported for channel={channel}",
        )

    chat_id = telegram_chat_id_from_external(
        str(external_id) if external_id is not None else None
    )
    if chat_id is None:
        raise HTTPException(
            status_code=400,
            detail="cannot resolve telegram chat_id from user external_id",
        )

    trace_id = getattr(request.state, "trace_id", None)
    msg_id = str(uuid.uuid4())
    script_id = data.used_script_id
    if script_id:
        try:
            uuid.UUID(script_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="used_script_id must be a UUID")

    await db.execute(
        text(
            """
            INSERT INTO messages (
              id, conversation_id, sender_type, sender_id, content, content_type,
              is_operator_message, used_script_id
            ) VALUES (
              :id, :cid, 'operator', :sid, :ct, 'text', true, :script
            )
            """
        ),
        {
            "id": msg_id,
            "cid": conv_id,
            "sid": operator_id,
            "ct": data.content,
            "script": script_id,
        },
    )
    await db.execute(
        text(
            "UPDATE conversations SET last_message_at=NOW(), updated_at=NOW() WHERE id=:id"
        ),
        {"id": conv_id},
    )

    tg_message_id = await send_telegram_text(
        chat_id=chat_id,
        text_content=data.content,
        trace_id=trace_id,
        parse_mode=None,
    )
    if tg_message_id is None:
        await db.rollback()
        logger.bind(
            trace_id=trace_id,
            task_id=task_id,
            conversation_id=conv_id,
            chat_id=chat_id,
        ).warning("handoff.reply.telegram_failed_rollback")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="telegram_send_failed",
        )

    await db.commit()

    try:
        redis = await get_redis()
        await _push_operator_context(redis, conv_id, data.content, msg_id)
    except Exception as exc:
        logger.warning(f"[{trace_id}] handoff.reply.redis_ctx_failed err={exc}")

    logger.bind(
        trace_id=trace_id,
        task_id=task_id,
        conversation_id=conv_id,
        message_id=msg_id,
        operator_id=operator_id,
        telegram_message_id=tg_message_id,
    ).info("handoff.reply.sent")

    return {
        "status": "sent",
        "task_id": task_id,
        "message_id": msg_id,
        "telegram_message_id": tg_message_id,
    }


@router.post("/{task_id}/return-ai")
async def return_to_ai(
    task_id: str,
    data: ReturnAIData,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    row = (
        await db.execute(
            text(
                """
                SELECT ht.user_id, ht.conversation_id
                FROM handoff_tasks ht
                WHERE ht.id = :tid
                """
            ),
            {"tid": task_id},
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="handoff task not found")

    user_id = str(row[0])
    conv_id = str(row[1])

    profile_row = (
        await db.execute(
            text(
                "SELECT relationship_stage, updated_at FROM user_profiles WHERE user_id=:uid"
            ),
            {"uid": user_id},
        )
    ).fetchone()
    profile = dict(profile_row._mapping) if profile_row else {}

    from services.risk_s5 import (
        RECOVERY_TARGET_STAGE,
        handoff_return_ai_block_reason,
        load_s5_restrictions,
    )

    s5 = await load_s5_restrictions(db, user_id=user_id, profile=profile)
    block = handoff_return_ai_block_reason(s5, allow_upsell=data.allow_upsell)
    if block:
        raise HTTPException(status_code=409, detail=block)

    await db.execute(
        text("UPDATE handoff_tasks SET status='CLOSED', closed_at=NOW() WHERE id=:id"),
        {"id": task_id},
    )
    if s5.active and s5.recovery_eligible:
        await db.execute(
            text(
                """
                UPDATE user_profiles
                SET relationship_stage = :stage, updated_at = NOW()
                WHERE user_id = :uid
                """
            ),
            {"stage": RECOVERY_TARGET_STAGE, "uid": user_id},
        )
        await db.execute(
            text(
                """
                UPDATE conversations
                SET state = 'AI_ACTIVE', updated_at = NOW()
                WHERE id = :cid
                """
            ),
            {"cid": conv_id},
        )
    await db.commit()

    logger.bind(
        task_id=task_id,
        user_id=user_id,
        s5_recovery_applied=bool(s5.active and s5.recovery_eligible),
    ).info("handoff.return_ai")

    return {
        "status": "returned_to_ai",
        "task_id": task_id,
        "s5_recovery_applied": bool(s5.active and s5.recovery_eligible),
    }


@router.post("/{task_id}/escalate")
async def escalate_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await db.execute(
        text("UPDATE handoff_tasks SET status='ESCALATED' WHERE id=:id"),
        {"id": task_id},
    )
    await db.commit()
    return {"status": "escalated", "task_id": task_id}
