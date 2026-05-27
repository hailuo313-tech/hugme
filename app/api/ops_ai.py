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


class OpsAiTranslateItem(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=4000)
    sender_type: Optional[str] = Field(default=None, max_length=32)


class OpsAiTranslateRequest(BaseModel):
    items: list[OpsAiTranslateItem] = Field(default_factory=list, max_length=50)
    target_language: str = Field(default="zh-CN", max_length=16)
    preserve_terms: list[str] = Field(default_factory=list, max_length=20)


class OpsAiTranslatedItem(BaseModel):
    id: str
    text: str


class OpsAiTranslateResponse(BaseModel):
    translations: list[OpsAiTranslatedItem]
    model_used: Optional[str] = None
    latency_ms: Optional[float] = None


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
    memories: list[dict[str, Any]],
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
        "user_level": conversation.get("user_level"),
        "chat_route": conversation.get("chat_route"),
        "country_code": conversation.get("country_code"),
        "character_name": conversation.get("character_name"),
        "language": conversation.get("language"),
        "chat_style": conversation.get("chat_style"),
        "interests": conversation.get("interests"),
        "preferences": conversation.get("preferences"),
        "emotional_patterns": conversation.get("emotional_patterns"),
        "notes": conversation.get("notes"),
        "forbidden_topics": conversation.get("forbidden_topics"),
    }
    personalization = {
        "must_use": [
            "Read the recent message history before drafting.",
            "Use the user's interests, hobbies, preferences, country, age, relationship stage, and memories when relevant.",
            "The reply must answer the user's latest message first, then naturally guide the business goal.",
            "Avoid generic replies that could fit any user.",
        ],
        "long_term_memories": [
            {
                "type": memory.get("memory_type"),
                "content": memory.get("content"),
                "summary": memory.get("summary"),
                "importance": memory.get("importance_score"),
                "emotion_tags": memory.get("emotion_tags"),
                "created_at": memory.get("created_at"),
            }
            for memory in memories
        ],
    }
    system = (
        "You are an operations assistant for a human operator. "
        "Summarize the conversation and draft exactly 3 candidate replies. "
        "Every candidate reply must be personalized from the user's actual chat history, interests, hobbies, profile preferences, and memories. "
        "Every candidate reply must include translation_zh, a Simplified Chinese reference translation for the human operator only. "
        "If the user has stated a preference or personal fact, reference it naturally when it helps the reply. "
        "Do not claim to be the user, the operator, a doctor, lawyer, or financial advisor. "
        "Do not promise refunds, bans, medical/legal/financial outcomes, or policy exceptions. "
        "Return strict JSON only, no markdown fences."
    )
    user = {
        "target_language": language,
        "tone": tone,
        "conversation_profile": profile,
        "personalization_context": personalization,
        "recent_messages_chronological": transcript or "(no messages)",
        "required_json_shape": {
            "summary": {
                "user_state": "string",
                "key_facts": ["string"],
                "risk_flags": ["string"],
                "recommended_strategy": "string",
            },
            "suggested_replies": [
                {"rank": 1, "text": "string", "translation_zh": "Simplified Chinese reference for operator", "reason": "string"},
                {"rank": 2, "text": "string", "translation_zh": "Simplified Chinese reference for operator", "reason": "string"},
                {"rank": 3, "text": "string", "translation_zh": "Simplified Chinese reference for operator", "reason": "string"},
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


def _normalize_translation_payload(
    parsed: dict[str, Any],
    requested_items: list[OpsAiTranslateItem],
) -> list[dict[str, str]]:
    raw_translations = parsed.get("translations")
    if not isinstance(raw_translations, list):
        raise ValueError("LLM response missing translations")

    requested_by_id = {item.id: item.text for item in requested_items}
    normalized_by_id: dict[str, str] = {}
    for item in raw_translations:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id not in requested_by_id:
            continue
        translated_text = str(item.get("text") or "").strip()
        normalized_by_id[item_id] = translated_text or requested_by_id[item_id]

    return [
        {"id": item.id, "text": normalized_by_id.get(item.id, item.text)}
        for item in requested_items
    ]


def _build_translation_messages(body: OpsAiTranslateRequest) -> list[dict[str, str]]:
    preserve_terms = [term for term in body.preserve_terms if term.strip()]
    payload = {
        "target_language": body.target_language,
        "preserve_terms": preserve_terms,
        "items": [
            {
                "id": item.id,
                "sender_type": item.sender_type,
                "text": item.text,
            }
            for item in body.items
        ],
        "required_json_shape": {
            "translations": [{"id": "same input id", "text": "Chinese translation"}]
        },
    }
    system = (
        "你是 ERIS 运营后台的只读翻译助手。"
        "把后台会话记录翻译成简体中文；已经是中文的内容保持原样。"
        "必须保留用户名、昵称、ID、URL、代码、金额、时间、表情和专有名词，不要增删事实。"
        "只返回严格 JSON，不要 Markdown，不要解释。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


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
        "translation_zh": templates[(rank - 1) % len(templates)],
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
        translation_value = str(reply.get("translation_zh") or "").strip()
        reason_value = str(reply.get("reason") or "").strip()
        if not text_value:
            continue
        normalized_replies.append(
            {
                "rank": len(normalized_replies) + 1,
                "text": text_value,
                "translation_zh": translation_value,
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
                  p.user_level,
                  p.chat_route,
                  p.country_code,
                  p.relationship_stage,
                  p.chat_style,
                  p.preferences,
                  p.interests,
                  p.emotional_patterns,
                  p.forbidden_topics,
                  p.notes,
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
    memory_rows = (
        await db.execute(
            text(
                """
                SELECT memory_type, content, summary, importance_score,
                       emotion_tags, created_at
                FROM memories
                WHERE user_id = CAST(:user_id AS uuid)
                  AND is_active = true
                ORDER BY importance_score DESC, created_at DESC
                LIMIT 12
                """
            ),
            {"user_id": str(conversation_row._mapping["user_id"])},
        )
    ).fetchall()
    conversation = _row_to_dict(conversation_row)
    recent_messages = [_row_to_dict(row) for row in reversed(msg_rows)]
    memories = [_row_to_dict(row) for row in memory_rows]
    llm_messages = _build_messages(
        conversation=conversation,
        messages=recent_messages,
        memories=memories,
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
        memories_used=len(memories),
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


@router.post("/translate", response_model=OpsAiTranslateResponse)
async def translate_admin_text(
    body: OpsAiTranslateRequest,
    request: Request,
    operator: dict = Depends(require_operator),
):
    started = time.time()
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    operator_id = operator.get("sub")
    items = [item for item in body.items if item.text.strip()]
    if not items:
        return {"translations": [], "model_used": None, "latency_ms": 0}

    normalized_body = body.model_copy(update={"items": items})
    logger.bind(
        operator_id=operator_id,
        item_count=len(items),
        target_language=body.target_language,
    ).info("ops_ai.translate.start")

    try:
        result = await llm_chat(
            messages=_build_translation_messages(normalized_body),
            trace_id=trace_id,
            temperature=0.1,
            max_tokens=1600,
        )
    except Exception as exc:
        logger.bind(
            operator_id=operator_id,
            item_count=len(items),
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=str(exc),
        ).warning("ops_ai.translate.llm_error")
        raise HTTPException(status_code=502, detail="翻译生成失败") from exc

    if result.error:
        logger.bind(
            operator_id=operator_id,
            item_count=len(items),
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=result.error,
        ).warning("ops_ai.translate.llm_error")
        raise HTTPException(status_code=502, detail="翻译生成失败")

    try:
        parsed = _extract_json_object(result.content)
        translations = _normalize_translation_payload(parsed, items)
    except ValueError as exc:
        logger.bind(
            operator_id=operator_id,
            item_count=len(items),
            elapsed_ms=round((time.time() - started) * 1000, 1),
            error=str(exc),
        ).warning("ops_ai.translate.parse_error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    elapsed_ms = round((time.time() - started) * 1000, 1)
    logger.bind(
        operator_id=operator_id,
        item_count=len(translations),
        model_used=result.model_used,
        elapsed_ms=elapsed_ms,
    ).info("ops_ai.translate.success")

    return {
        "translations": translations,
        "model_used": result.model_used,
        "latency_ms": elapsed_ms,
    }
