"""Coalesce rapid inbound user messages into one outbound reply turn."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

_COALESCE_KEY_PREFIX = "mtproto:inbound_coalesce"
_REPLY_LOCK_PREFIX = "mtproto:inbound_reply_lock"
_DEFAULT_DEBOUNCE_SECONDS = 4.0
_BATCH_TTL_SECONDS = 120
_REPLY_LOCK_TTL_SECONDS = 180


@dataclass(frozen=True)
class CoalescedInboundTurn:
    should_reply: bool
    merged_text: str
    trigger_message_id: str
    message_ids: tuple[str, ...]
    message_count: int
    trace_id: str


@dataclass(frozen=True)
class CoalescedInboundRegistration:
    epoch: int
    started_at: float


def coalesce_debounce_seconds() -> float:
    raw = getattr(settings, "MTProto_INBOUND_COALESCE_SECONDS", _DEFAULT_DEBOUNCE_SECONDS)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_DEBOUNCE_SECONDS


def merge_coalesced_user_text(parts: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = str(part or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return "\n".join(cleaned)


def _batch_key(conversation_id: str) -> str:
    return f"{_COALESCE_KEY_PREFIX}:{conversation_id}:batch"


def _epoch_key(conversation_id: str) -> str:
    return f"{_COALESCE_KEY_PREFIX}:{conversation_id}:epoch"


def _reply_lock_key(conversation_id: str) -> str:
    return f"{_REPLY_LOCK_PREFIX}:{conversation_id}"


async def try_acquire_inbound_reply_lock(
    redis: Any,
    *,
    conversation_id: str,
    owner_message_id: str,
) -> bool:
    """One active auto-reply pipeline per conversation."""
    acquired = await redis.set(
        _reply_lock_key(conversation_id),
        owner_message_id,
        nx=True,
        ex=_REPLY_LOCK_TTL_SECONDS,
    )
    return bool(acquired)


async def release_inbound_reply_lock(
    redis: Any,
    *,
    conversation_id: str,
    owner_message_id: str,
) -> None:
    key = _reply_lock_key(conversation_id)
    current = await redis.get(key)
    if current is None:
        return
    if str(current) == owner_message_id:
        await redis.delete(key)


def _db_naive_utc(value: datetime) -> datetime:
    """Normalize to naive UTC for TIMESTAMP WITHOUT TIME ZONE columns."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def _message_created_at(
    db: AsyncSession,
    message_id: str,
) -> datetime | None:
    row = (
        await db.execute(
            text(
                """
                SELECT created_at
                FROM messages
                WHERE id = CAST(:message_id AS uuid)
                LIMIT 1
                """
            ),
            {"message_id": message_id},
        )
    ).first()
    if row is None:
        return None
    created_at = row[0]
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            return created_at.replace(tzinfo=timezone.utc)
        return created_at.astimezone(timezone.utc)
    return None


async def _wait_for_quiet_period(
    db: AsyncSession,
    redis: Any,
    *,
    conversation_id: str,
    registration: CoalescedInboundRegistration,
    fallback_message_id: str,
    fallback_text: str,
    sleep: Any,
) -> tuple[list[dict[str, str]], bool]:
    """Wait debounce seconds after the latest unreplied user message; defer if epoch advances."""
    debounce = coalesce_debounce_seconds()
    for _ in range(6):
        current_epoch = int(await redis.get(_epoch_key(conversation_id)) or 0)
        if current_epoch != registration.epoch:
            return [], False

        unreplied = await _load_unreplied_user_messages(db, conversation_id=conversation_id)
        if not unreplied:
            unreplied = [{"message_id": fallback_message_id, "text": fallback_text}]

        latest_id = unreplied[-1]["message_id"]
        latest_at = await _message_created_at(db, latest_id) or datetime.now(timezone.utc)
        quiet_until = latest_at + timedelta(seconds=debounce)
        remaining = (quiet_until - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            await sleep(remaining)

        current_epoch = int(await redis.get(_epoch_key(conversation_id)) or 0)
        if current_epoch != registration.epoch:
            return [], False

        unreplied = await _load_unreplied_user_messages(db, conversation_id=conversation_id)
        if not unreplied:
            unreplied = [{"message_id": fallback_message_id, "text": fallback_text}]
        latest_id = unreplied[-1]["message_id"]
        latest_at = await _message_created_at(db, latest_id) or datetime.now(timezone.utc)
        if datetime.now(timezone.utc) >= latest_at + timedelta(seconds=debounce):
            return unreplied, True

    return [], False


async def register_inbound_turn(
    redis: Any,
    *,
    conversation_id: str,
    message_id: str,
    text_value: str,
    trace_id: str,
) -> CoalescedInboundRegistration:
    payload = json.dumps(
        {
            "message_id": message_id,
            "text": text_value,
            "trace_id": trace_id,
        },
        ensure_ascii=False,
    )
    pipe = redis.pipeline()
    pipe.rpush(_batch_key(conversation_id), payload)
    pipe.expire(_batch_key(conversation_id), _BATCH_TTL_SECONDS)
    pipe.incr(_epoch_key(conversation_id))
    pipe.expire(_epoch_key(conversation_id), _BATCH_TTL_SECONDS)
    results = await pipe.execute()
    return CoalescedInboundRegistration(
        epoch=int(results[-2]),
        started_at=time.monotonic(),
    )


async def _load_unreplied_user_messages(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, content
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND sender_type = 'user'
                  AND created_at > COALESCE(
                    (
                      SELECT MAX(created_at)
                      FROM messages
                      WHERE conversation_id = CAST(:conversation_id AS uuid)
                        AND sender_type = 'assistant'
                    ),
                    TIMESTAMPTZ '1970-01-01'
                  )
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"conversation_id": conversation_id},
        )
    ).mappings().all()
    return [
        {"message_id": str(row["id"]), "text": str(row["content"] or "")}
        for row in rows
    ]


async def inbound_reply_turn_stale(
    db: AsyncSession,
    *,
    conversation_id: str,
    trigger_message_id: str,
    claimed_message_ids: tuple[str, ...],
) -> bool:
    """True when another handler already replied or newer user text superseded this turn."""
    unreplied = await _load_unreplied_user_messages(db, conversation_id=conversation_id)
    current_ids = tuple(row["message_id"] for row in unreplied)
    if current_ids != claimed_message_ids:
        return True
    if not current_ids or current_ids[-1] != trigger_message_id:
        return True

    trigger_row = (
        await db.execute(
            text(
                """
                SELECT created_at
                FROM messages
                WHERE id = CAST(:message_id AS uuid)
                LIMIT 1
                """
            ),
            {"message_id": trigger_message_id},
        )
    ).first()
    if trigger_row is None:
        return True
    trigger_at = trigger_row[0]
    if not isinstance(trigger_at, datetime):
        return True
    trigger_at = _db_naive_utc(trigger_at)

    already_replied = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM messages
                WHERE conversation_id = CAST(:conversation_id AS uuid)
                  AND sender_type = 'assistant'
                  AND created_at > :trigger_at
                LIMIT 1
                """
            ),
            {
                "conversation_id": conversation_id,
                "trigger_at": trigger_at,
            },
        )
    ).first()
    return already_replied is not None


async def finalize_coalesced_inbound_turn(
    redis: Any,
    db: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    text_value: str,
    trace_id: str,
    registration: CoalescedInboundRegistration | None,
    sleep: Any,
) -> CoalescedInboundTurn:
    """Finish debounce window and decide whether this handler sends the merged reply."""
    debounce = coalesce_debounce_seconds()
    if debounce <= 0:
        return CoalescedInboundTurn(
            should_reply=True,
            merged_text=text_value,
            trigger_message_id=message_id,
            message_ids=(message_id,),
            message_count=1,
            trace_id=trace_id,
        )

    registration = registration or await register_inbound_turn(
        redis,
        conversation_id=conversation_id,
        message_id=message_id,
        text_value=text_value,
        trace_id=trace_id,
    )

    unreplied, ready = await _wait_for_quiet_period(
        db,
        redis,
        conversation_id=conversation_id,
        registration=registration,
        fallback_message_id=message_id,
        fallback_text=text_value,
        sleep=sleep,
    )
    if not ready:
        logger.bind(
            component="inbound_reply_coalescer",
            conversation_id=conversation_id,
            message_id=message_id,
            epoch=registration.epoch,
        ).info("inbound_reply_coalescer.deferred_to_later_turn")
        return CoalescedInboundTurn(
            should_reply=False,
            merged_text=text_value,
            trigger_message_id=message_id,
            message_ids=(message_id,),
            message_count=1,
            trace_id=trace_id,
        )

    merged_text = merge_coalesced_user_text([row["text"] for row in unreplied])
    message_ids = tuple(row["message_id"] for row in unreplied)
    trigger_message_id = message_ids[-1]
    latest_trace = trace_id
    try:
        raw_items = await redis.lrange(_batch_key(conversation_id), 0, -1)
        for raw in reversed(raw_items or []):
            item = json.loads(raw)
            if str(item.get("message_id") or "") == trigger_message_id:
                latest_trace = str(item.get("trace_id") or trace_id)
                break
    except Exception:
        latest_trace = trace_id

    await redis.delete(_batch_key(conversation_id), _epoch_key(conversation_id))

    logger.bind(
        component="inbound_reply_coalescer",
        conversation_id=conversation_id,
        message_count=len(message_ids),
        trigger_message_id=trigger_message_id,
    ).info("inbound_reply_coalescer.merged_turn")

    return CoalescedInboundTurn(
        should_reply=True,
        merged_text=merged_text or text_value,
        trigger_message_id=trigger_message_id,
        message_ids=message_ids,
        message_count=len(message_ids),
        trace_id=latest_trace,
    )


async def await_coalesced_inbound_turn(
    redis: Any,
    db: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    text_value: str,
    trace_id: str,
    sleep: Any,
) -> CoalescedInboundTurn:
    """Register and finalize in one call (tests / legacy callers)."""
    registration = await register_inbound_turn(
        redis,
        conversation_id=conversation_id,
        message_id=message_id,
        text_value=text_value,
        trace_id=trace_id,
    )
    return await finalize_coalesced_inbound_turn(
        redis,
        db,
        conversation_id=conversation_id,
        message_id=message_id,
        text_value=text_value,
        trace_id=trace_id,
        registration=registration,
        sleep=sleep,
    )
