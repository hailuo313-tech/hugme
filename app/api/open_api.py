"""P3 public App/Web/Open API surface.

This router intentionally exposes a narrow client-facing contract and reuses the
existing safety, memory, consistency, and LLM orchestration services instead of
duplicating the chat stack.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.telegram import get_redis, _persist_message, _push_context
from core.config import settings
from core.database import get_db
from services.content_safety import evaluate_inbound_content_safety
from services.llm_orchestrator import LLMOrchestratorError, generate_reply
from services.memory_writer import maybe_write_memory
from services.minor_protection import evaluate_inbound_minor_protection
from services.reply_consistency import (
    evaluate_reply_consistency,
    load_reply_consistency_context,
)

router = APIRouter()

SAFE_PROFILE_KEYS = {"chat_style", "interests", "current_intent"}
AI_ACTIVE = "AI_ACTIVE"


class OpenCharacter(BaseModel):
    id: str
    name: str
    age_feel: Optional[str] = None
    region: Optional[str] = None
    occupation: Optional[str] = None
    background: Optional[str] = None
    relationship_position: Optional[str] = None
    default_language: Optional[str] = None
    supported_languages: list[str] = Field(default_factory=list)
    tone: Optional[str] = None
    reply_length: Optional[str] = None


class OpenCurrentCharacter(BaseModel):
    id: str
    name: str


class OpenOnboarding(BaseModel):
    step: int
    completed: bool


class OpenUserProfile(BaseModel):
    user_id: str
    nickname: Optional[str] = None
    language: str
    timezone: str
    relationship_stage: str
    current_character: Optional[OpenCurrentCharacter] = None
    onboarding: OpenOnboarding
    preferences: dict[str, Any] = Field(default_factory=dict)


class OpenConversationCreate(BaseModel):
    user_id: str
    character_id: str
    channel: str = Field(default="web", max_length=20)


class OpenConversationResponse(BaseModel):
    conversation_id: str
    user_id: str
    character_id: str
    state: str


class OpenMessageCreate(BaseModel):
    user_id: str
    content: str = Field(min_length=1, max_length=8000)
    content_type: str = Field(default="text", max_length=20)


class OpenMessageSummary(BaseModel):
    id: str
    content: str
    created_at: Optional[str] = None


class OpenSafetySummary(BaseModel):
    blocked: bool = False
    reason: Optional[str] = None


class OpenSendMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    user_message: OpenMessageSummary
    assistant_message: Optional[OpenMessageSummary] = None
    safety: OpenSafetySummary
    trace_id: str


class OpenConversationMessage(BaseModel):
    id: str
    sender_type: Optional[str] = None
    content: Optional[str] = None
    content_type: str = "text"
    created_at: Optional[str] = None


class OpenConversationMessagesResponse(BaseModel):
    items: list[OpenConversationMessage]
    has_more: bool


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {field_name}",
        )


def _mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return row
    return {}


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _ensure_header_user(user_id: str, x_user_id: Optional[str]) -> str:
    uid = _validate_uuid(user_id, "user_id")
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing X-User-Id")
    header_uid = _validate_uuid(x_user_id, "X-User-Id")
    if header_uid != uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user mismatch")
    return uid


def _ensure_optional_header_user(user_id: str, x_user_id: Optional[str]) -> str:
    uid = _validate_uuid(user_id, "user_id")
    if x_user_id:
        header_uid = _validate_uuid(x_user_id, "X-User-Id")
        if header_uid != uid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user mismatch")
    return uid


def _public_character(row: dict[str, Any]) -> OpenCharacter:
    return OpenCharacter(
        id=str(row.get("id")),
        name=str(row.get("name") or ""),
        age_feel=row.get("age_feel"),
        region=row.get("region"),
        occupation=row.get("occupation"),
        background=row.get("background"),
        relationship_position=row.get("relationship_position"),
        default_language=row.get("default_language"),
        supported_languages=[str(x) for x in _json_list(row.get("supported_languages"))],
        tone=row.get("tone"),
        reply_length=row.get("reply_length"),
    )


def _safe_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    prefs = _json_dict(profile.get("preferences"))
    safe = {k: prefs[k] for k in SAFE_PROFILE_KEYS if k in prefs}
    if profile.get("chat_style"):
        safe["chat_style"] = profile.get("chat_style")
    interests = _json_list(profile.get("interests"))
    if interests:
        safe["interests"] = interests
    return safe


def _safety_reason(safety_result: Optional[dict[str, Any]]) -> Optional[str]:
    if not safety_result:
        return None
    reason = safety_result.get("block_reason")
    minor = safety_result.get("minor_protection")
    if not reason and isinstance(minor, dict):
        reason = minor.get("reason")
    return reason


@router.get("/characters", response_model=list[OpenCharacter])
async def list_open_characters(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        text(
            """
            SELECT id::text AS id, name, age_feel, region, occupation, background,
                   relationship_position, default_language, supported_languages,
                   tone, reply_length
            FROM characters
            WHERE status='active'
            ORDER BY name ASC
            """
        )
    )
    return [_public_character(_mapping(row)) for row in res.fetchall()]


@router.get("/users/{user_id}/profile", response_model=OpenUserProfile)
async def get_open_user_profile(
    user_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    uid = _ensure_header_user(user_id, x_user_id)
    row = (
        await db.execute(
            text(
                """
                SELECT u.id::text AS user_id, u.nickname, u.language, u.timezone,
                       COALESCE(p.relationship_stage, 'S0') AS relationship_stage,
                       p.preferences, p.interests, p.chat_style,
                       c.id::text AS character_id, c.name AS character_name
                FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                LEFT JOIN characters c ON c.id = p.current_character_id
                WHERE u.id = CAST(:uid AS uuid)
                """
            ),
            {"uid": uid},
        )
    ).fetchone()
    data = _mapping(row)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    prefs = _json_dict(data.get("preferences"))
    step = int(prefs.get("onboarding_step") or 0)
    current_character = None
    if data.get("character_id"):
        current_character = OpenCurrentCharacter(
            id=str(data["character_id"]),
            name=str(data.get("character_name") or "Unknown"),
        )
    return OpenUserProfile(
        user_id=uid,
        nickname=data.get("nickname"),
        language=str(data.get("language") or "en"),
        timezone=str(data.get("timezone") or "UTC"),
        relationship_stage=str(data.get("relationship_stage") or "S0"),
        current_character=current_character,
        onboarding=OpenOnboarding(step=step, completed=step >= 6),
        preferences=_safe_preferences(data),
    )


@router.post(
    "/conversations",
    response_model=OpenConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_open_conversation(
    body: OpenConversationCreate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    uid = _ensure_optional_header_user(body.user_id, x_user_id)
    cid = _validate_uuid(body.character_id, "character_id")

    user_row = (
        await db.execute(
            text("SELECT id::text AS id, status FROM users WHERE id = CAST(:uid AS uuid)"),
            {"uid": uid},
        )
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if str(_mapping(user_row).get("status") or "active") != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is not active")

    char_row = (
        await db.execute(
            text(
                "SELECT id::text AS id FROM characters "
                "WHERE id = CAST(:cid AS uuid) AND status='active'"
            ),
            {"cid": cid},
        )
    ).fetchone()
    if not char_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    existing = (
        await db.execute(
            text(
                """
                SELECT id::text AS id, state
                FROM conversations
                WHERE user_id = CAST(:uid AS uuid)
                  AND character_id = CAST(:cid AS uuid)
                  AND state = :state
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {"uid": uid, "cid": cid, "state": AI_ACTIVE},
        )
    ).fetchone()
    if existing:
        existing_data = _mapping(existing)
        return OpenConversationResponse(
            conversation_id=str(existing_data.get("id")),
            user_id=uid,
            character_id=cid,
            state=str(existing_data.get("state") or AI_ACTIVE),
        )

    conv_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO conversations (id, user_id, character_id, channel, state)
            VALUES (:id, CAST(:uid AS uuid), CAST(:cid AS uuid), :channel, :state)
            """
        ),
        {"id": conv_id, "uid": uid, "cid": cid, "channel": body.channel, "state": AI_ACTIVE},
    )
    await db.commit()
    return OpenConversationResponse(
        conversation_id=conv_id,
        user_id=uid,
        character_id=cid,
        state=AI_ACTIVE,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=OpenSendMessageResponse,
)
async def send_open_message(
    conversation_id: str,
    body: OpenMessageCreate,
    request: Request,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    start_ts = time.time()
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    conv_id = _validate_uuid(conversation_id, "conversation_id")
    uid = _ensure_optional_header_user(body.user_id, x_user_id)
    log = logger.bind(trace_id=trace_id, user_id=uid, conversation_id=conv_id)

    conv_row = (
        await db.execute(
            text(
                """
                SELECT c.id::text AS id, c.user_id::text AS user_id, c.state, u.is_minor_suspected,
                       u.status AS user_status
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": conv_id},
        )
    ).fetchone()
    conv = _mapping(conv_row)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if str(conv.get("user_id")) != uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="conversation user mismatch")
    if str(conv.get("user_status") or "active") != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user is not active")
    if str(conv.get("state") or "") != AI_ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conversation is not AI active")

    text_content = body.content.strip()
    content_type = (body.content_type or "text").strip().lower()
    if content_type != "text":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="only text messages are supported in the P3 MVP",
        )
    safety_result: Optional[dict[str, Any]] = None
    safety_blocked = False
    minor_decision = await evaluate_inbound_minor_protection(
        db,
        user_id=uid,
        text_value=text_content,
        is_minor_suspected=bool(conv.get("is_minor_suspected")),
    )
    if (
        minor_decision.suspected_minor
        or minor_decision.adult_content
        or minor_decision.updated_user
    ):
        safety_result = minor_decision.as_safety_layer()
    safety_blocked = bool(minor_decision.blocked)

    if settings.CONTENT_SAFETY_ENABLED:
        content_safety = await evaluate_inbound_content_safety(text_content, trace_id=trace_id, skip_sexual_block=True)  # premium_nsfw_companion 模式下跳过 sexual 拦截
        if safety_result is None:
            safety_result = content_safety
        else:
            safety_result = {
                **content_safety,
                "minor_protection": safety_result.get("minor_protection"),
            }
        safety_blocked = safety_blocked or bool(content_safety.get("blocked"))

    user_msg_id = await _persist_message(
        db,
        conv_id,
        "user",
        uid,
        text_content,
        safety_result=safety_result,
    )
    user_created_at = datetime.utcnow().isoformat()
    log.bind(message_id=user_msg_id).info("open.message.persisted")

    if safety_blocked:
        reason = _safety_reason(safety_result) or "blocked_by_safety"
        log.bind(block_reason=reason).info("open.message.blocked_by_safety")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message_id": user_msg_id,
                "conversation_id": conv_id,
                "safety": {"blocked": True, "reason": reason},
                "trace_id": trace_id,
            },
        )

    redis = await get_redis()
    try:
        await _push_context(redis, conv_id, "user", text_content, user_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("open.context.push_user_failed")

    try:
        asyncio.create_task(
            maybe_write_memory(
                user_id=uid,
                conversation_id=conv_id,
                message_id=user_msg_id,
                content=text_content,
                trace_id=trace_id,
                redis=redis,
            )
        )
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("open.memory_writer.spawn_failed")

    try:
        reply_text = await generate_reply(
            user_id=uid,
            conversation_id=conv_id,
            user_text=text_content,
            trace_id=trace_id,
            redis=redis,
            db=db,
            trigger_message_id=user_msg_id,
        )
    except LLMOrchestratorError as exc:
        log.bind(result="failed", reason=str(exc)).warning("open.orchestrator.failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "AI upstream unavailable", "trace_id": trace_id},
        )

    try:
        ctx = await load_reply_consistency_context(db, conv_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("open.consistency.context_failed")
        ctx = {}
    consistency = evaluate_reply_consistency(
        reply_text=reply_text,
        character=ctx.get("character"),
    )
    assistant_text = consistency.output_text
    assistant_msg_id = await _persist_message(
        db,
        conv_id,
        "assistant",
        "bot",
        assistant_text,
        consistency_score=consistency.score,
    )
    assistant_created_at = datetime.utcnow().isoformat()
    try:
        await _push_context(redis, conv_id, "assistant", assistant_text, assistant_msg_id)
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("open.context.push_assistant_failed")

    elapsed_ms = round((time.time() - start_ts) * 1000, 1)
    log.bind(
        message_id=user_msg_id,
        assistant_message_id=assistant_msg_id,
        elapsed_ms=elapsed_ms,
    ).info("open.message.complete")

    return OpenSendMessageResponse(
        message_id=user_msg_id,
        conversation_id=conv_id,
        user_message=OpenMessageSummary(
            id=user_msg_id,
            content=text_content,
            created_at=user_created_at,
        ),
        assistant_message=OpenMessageSummary(
            id=assistant_msg_id,
            content=assistant_text,
            created_at=assistant_created_at,
        ),
        safety=OpenSafetySummary(blocked=False, reason=None),
        trace_id=trace_id,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=OpenConversationMessagesResponse,
)
async def list_open_conversation_messages(
    conversation_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    limit: int = Query(default=50, ge=1, le=100),
    before: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    conv_id = _validate_uuid(conversation_id, "conversation_id")
    if before:
        before = _validate_uuid(before, "before")
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing X-User-Id")
    header_uid = _validate_uuid(x_user_id, "X-User-Id")

    conv_row = (
        await db.execute(
            text("SELECT user_id::text AS user_id FROM conversations WHERE id = CAST(:cid AS uuid)"),
            {"cid": conv_id},
        )
    ).fetchone()
    conv = _mapping(conv_row)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if str(conv.get("user_id")) != header_uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="conversation user mismatch")

    params: dict[str, Any] = {"cid": conv_id, "limit": limit + 1}
    before_clause = ""
    if before:
        params["before"] = before
        before_clause = (
            "AND created_at < (SELECT created_at FROM messages "
            "WHERE id = CAST(:before AS uuid) AND conversation_id = CAST(:cid AS uuid))"
        )
    res = await db.execute(
        text(
            f"""
            SELECT id::text AS id, sender_type, content, content_type, created_at
            FROM messages
            WHERE conversation_id = CAST(:cid AS uuid)
              {before_clause}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    rows = [_mapping(row) for row in res.fetchall()]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return OpenConversationMessagesResponse(
        items=[
            OpenConversationMessage(
                id=str(row.get("id")),
                sender_type=row.get("sender_type"),
                content=row.get("content"),
                content_type=str(row.get("content_type") or "text"),
                created_at=_ts(row.get("created_at")),
            )
            for row in rows
        ],
        has_more=has_more,
    )
