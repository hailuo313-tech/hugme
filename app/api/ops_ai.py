from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from services.llm import chat as llm_chat

router = APIRouter()


class OpsAiAssistRequest(BaseModel):
    handoff_task_id: Optional[str] = None
    language: str = "zh-CN"
    tone: Literal["warm", "professional", "concise"] = "warm"
    max_context_messages: int = Field(default=30, ge=1, le=80)

    @field_validator("handoff_task_id")
    @classmethod
    def _validate_handoff_task_id(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        try:
            return str(uuid.UUID(str(value)))
        except ValueError as exc:
            raise ValueError("handoff_task_id must be a valid UUID") from exc


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be a valid UUID",
        ) from exc


def _row_to_dict(row: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in dict(row._mapping).items():
        if hasattr(value, "isoformat") and callable(getattr(value, "isoformat")):
            data[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            data[key] = str(value)
        else:
            data[key] = value
    return data


def _build_messages(
    *,
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    language: str,
    tone: str,
) -> list[dict[str, str]]:
    transcript = "\n".join(
        f"[{m.get('created_at') or '-'}] {m.get('sender_type') or 'unknown'}: {m.get('content') or ''}"
        for m in messages
    )
    profile = {
        "nickname": conversation.get("nickname"),
        "risk_level": conversation.get("risk_level"),
        "relationship_stage": conversation.get("relationship_stage"),
        "vip_level": conversation.get("vip_level"),
        "character_name": conversation.get("character_name"),
        "language": conversation.get("language"),
        "chat_style": conversation.get("chat_style"),
        "interests": conversation.get("interests"),
        "forbidden_topics": conversation.get("forbidden_topics"),
    }
    system = (
        "You are an operations assistant for a human operator. "
        "Summarize the conversation and draft exactly 3 candidate replies. "
        "Do not claim to be the user, the operator, a doctor, lawyer, or financial advisor. "
        "Do not promise refunds, bans, medical/legal/financial outcomes, or policy exceptions. "
        "Return strict JSON only, no markdown fences."
    )
    user = {
        "target_language": language,
        "tone": tone,
        "conversation_profile": profile,
        "recent_messages_chronological": transcript or "(no messages)",
        "required_json_shape": {
            "summary": {
                "user_state": "string",
                "key_facts": ["string"],
                "risk_flags": ["string"],
                "recommended_strategy": "string",
            },
            "suggested_replies": [
                {"rank": 1, "text": "string", "reason": "string"},
                {"rank": 2, "text": "string", "reason": "string"},
                {"rank": 3, "text": "string", "reason": "string"},
            ],
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _extract_json_object(content: str) -> dict[str, Any]:
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _fallback_reply(rank: int, summary: dict[str, Any]) -> dict[str, Any]:
    strategy = str(summary.get("recommended_strategy") or "").strip()
    templates = [
        "我在的，也谢谢你把感受告诉我。我会先认真理解你的情况，再一步步处理。",
        "我理解这件事会让你不安。我们先把最重要的问题确认清楚，再决定下一步。",
        "谢谢你愿意继续说。我会用更稳妥的方式陪你把这件事梳理清楚。",
    ]
    return {
        "rank": rank,
        "text": templates[(rank - 1) % len(templates)],
        "reason": strategy or "LLM 返回不足 3 条时的安全补位回复。",
    }


def _normalize_assist_payload(parsed: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = parsed.get("summary")
    replies = parsed.get("suggested_replies")
    if not isinstance(summary, dict) or not isinstance(replies, list):
        raise ValueError("LLM response missing summary or suggested_replies")

    normalized_summary = {
        "user_state": str(summary.get("user_state") or "").strip(),
        "key_facts": [str(item).strip() for item in (summary.get("key_facts") or []) if str(item).strip()],
        "risk_flags": [str(item).strip() for item in (summary.get("risk_flags") or []) if str(item).strip()],
        "recommended_strategy": str(summary.get("recommended_strategy") or "").strip(),
    }
    normalized_replies: list[dict[str, Any]] = []
    for reply in replies[:3]:
        if not isinstance(reply, dict):
            continue
        text_value = str(reply.get("text") or "").strip()
        reason_value = str(reply.get("reason") or "").strip()
        if not text_value:
            continue
        normalized_replies.append(
            {
                "rank": len(normalized_replies) + 1,
                "text": text_value,
                "reason": reason_value,
            }
        )
    while len(normalized_replies) < 3:
        normalized_replies.append(_fallback_reply(len(normalized_replies) + 1, normalized_summary))
    return normalized_summary, normalized_replies


@router.post("/conversations/{conversation_id}/assist")
async def assist_conversation(
    conversation_id: str,
    body: OpsAiAssistRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    cid = _validate_uuid(conversation_id, "conversation_id")
    started = time.time()
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    operator_id = operator.get("sub")
    logger.bind(
        operator_id=operator_id,
        conversation_id=cid,
        handoff_task_id=body.handoff_task_id,
        max_context_messages=body.max_context_messages,
    ).info("ops_ai.assist.start")

    conversation_row = (
        await db.execute(
            text(
                """
                SELECT
                  c.id AS conversation_id,
                  c.state,
                  c.channel,
                  c.last_message_at,
                  c.created_at,
                  u.id AS user_id,
                  u.nickname,
                  u.external_id,
                  u.risk_level,
                  u.language,
                  p.loneliness_score,
                  p.vip_level,
                  p.relationship_stage,
                  p.chat_style,
                  p.interests,
                  p.forbidden_topics,
                  ch.id AS character_id,
                  ch.name AS character_name
                FROM conversations c
                LEFT JOIN users u ON u.id = c.user_id
                LEFT JOIN user_profiles p ON p.user_id = u.id
                LEFT JOIN characters ch ON ch.id = c.character_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": cid},
        )
    ).fetchone()
    if conversation_row is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg_rows = (
        await db.execute(
            text(
                """
                SELECT id, sender_type, content, content_type,
                       is_operator_message, model_name, created_at
                FROM messages
                WHERE conversation_id = CAST(:cid AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"cid": cid, "limit": body.max_context_messages},
        )
    ).fetchall()
    conversation = _row_to_dict(conversation_row)
    recent_messages = [_row_to_dict(row) for row in reversed(msg_rows)]
    llm_messages = _build_messages(
        conversation=conversation,
        messages=recent_messages,
        language=body.language,
        tone=body.tone,
    )

    try:
        result = await llm_chat(
            messages=llm_messages,
            trace_id=trace_id,
            temperature=0.35,
            max_tokens=900,
        )
    except Exception as exc:
        logger.bind(
            operator_id=operator_id,
            conversation_id=cid,
            handoff_task_id=body.handoff_task_id,
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=str(exc),
        ).warning("ops_ai.assist.llm_error")
        raise HTTPException(status_code=502, detail="AI assist generation failed") from exc

    if result.error:
        logger.bind(
            operator_id=operator_id,
            conversation_id=cid,
            handoff_task_id=body.handoff_task_id,
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=result.error,
        ).warning("ops_ai.assist.llm_error")
        raise HTTPException(status_code=502, detail="AI assist generation failed")

    try:
        parsed = _extract_json_object(result.content)
        summary, suggested_replies = _normalize_assist_payload(parsed)
    except ValueError as exc:
        logger.bind(
            operator_id=operator_id,
            conversation_id=cid,
            handoff_task_id=body.handoff_task_id,
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=str(exc),
        ).warning("ops_ai.assist.llm_error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    elapsed_ms = round((time.time() - started) * 1000, 1)
    logger.bind(
        operator_id=operator_id,
        conversation_id=cid,
        handoff_task_id=body.handoff_task_id,
        messages_used=len(recent_messages),
        model_used=result.model_used,
        elapsed_ms=elapsed_ms,
    ).info("ops_ai.assist.success")

    return {
        "conversation_id": cid,
        "handoff_task_id": body.handoff_task_id,
        "summary": summary,
        "suggested_replies": suggested_replies,
        "model_used": result.model_used,
        "latency_ms": elapsed_ms,
    }
