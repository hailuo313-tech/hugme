"""Redis conversation context helpers for P1-19."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

CONVERSATION_CONTEXT_PREFIX = "conv:"
CONVERSATION_CONTEXT_MAX_MESSAGES = 100
CONVERSATION_CONTEXT_DEFAULT_READ_LIMIT = 50
CONVERSATION_CONTEXT_TTL_SECONDS = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class ConversationContextItem:
    role: str
    content: str
    msg_id: Optional[str] = None
    ts: Optional[int] = None

    def to_redis_json(self) -> str:
        payload: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "ts": self.ts if self.ts is not None else int(time.time()),
        }
        if self.msg_id:
            payload["msg_id"] = self.msg_id
        return json.dumps(payload, ensure_ascii=False)


def conversation_context_key(user_id: str | int) -> str:
    user_key = str(user_id)
    if not user_key:
        raise ValueError("user_id is required")
    return f"{CONVERSATION_CONTEXT_PREFIX}{user_key}"


def _normalize_role(role: Any) -> Optional[str]:
    if not isinstance(role, str):
        return None
    role = role.strip().lower()
    if role in {"user", "assistant", "system"}:
        return role
    if role in {"bot", "ai"}:
        return "assistant"
    return None


def _decode_raw_item(raw: Any) -> Optional[ConversationContextItem]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    role = _normalize_role(data.get("role"))
    content = data.get("content")
    if not role or not isinstance(content, str) or not content:
        return None
    ts = data.get("ts")
    return ConversationContextItem(
        role=role,
        content=content,
        msg_id=data.get("msg_id") if isinstance(data.get("msg_id"), str) else None,
        ts=ts if isinstance(ts, int) else None,
    )


async def append_conversation_context(
    redis: Any,
    *,
    user_id: str | int,
    role: str,
    content: str,
    msg_id: Optional[str] = None,
    max_messages: int = CONVERSATION_CONTEXT_MAX_MESSAGES,
    ttl_seconds: int = CONVERSATION_CONTEXT_TTL_SECONDS,
) -> str:
    """Append one message to conv:{user_id}, retaining 50 turns / 100 messages."""
    key = conversation_context_key(user_id)
    entry = ConversationContextItem(role=role, content=content, msg_id=msg_id).to_redis_json()
    pipe = redis.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -max_messages, -1)
    pipe.expire(key, ttl_seconds)
    await pipe.execute()
    return key


async def load_conversation_context(
    redis: Any,
    *,
    user_id: str | int,
    limit: int = CONVERSATION_CONTEXT_DEFAULT_READ_LIMIT,
    drop_latest: bool = False,
) -> list[dict[str, str]]:
    """Read recent conv:{user_id} context in chronological order for LLM messages."""
    if limit <= 0:
        return []
    read_count = limit + 1 if drop_latest else limit
    raw_items = await redis.lrange(conversation_context_key(user_id), -read_count, -1)
    if drop_latest and raw_items:
        raw_items = raw_items[:-1]

    parsed: list[dict[str, str]] = []
    for raw in raw_items or []:
        item = _decode_raw_item(raw)
        if item is not None:
            parsed.append({"role": item.role, "content": item.content})
    return parsed[-limit:]
