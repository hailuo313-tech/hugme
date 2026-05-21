"""Audit log persistence and recent-query helpers for P1-16."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


RECENT_AUDIT_LIMIT = 100


def _redact_phone(value: Any) -> str | None:
    if value in (None, ""):
        return None
    phone = str(value)
    if len(phone) <= 4:
        return "****"
    return f"{'*' * max(len(phone) - 4, 4)}{phone[-4:]}"


def _json_payload(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True)


def _row_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping
    raise TypeError(f"unsupported audit row type: {type(row)!r}")


def serialize_audit_row(row: Any) -> dict[str, Any]:
    data = dict(_row_mapping(row))
    payload = data.get("payload")
    if isinstance(payload, str):
        try:
            data["payload"] = json.loads(payload)
        except json.JSONDecodeError:
            data["payload"] = {"raw": payload}
    data["sender_phone"] = _redact_phone(data.get("sender_phone"))
    created_at = data.get("created_at")
    if hasattr(created_at, "isoformat"):
        data["created_at"] = created_at.isoformat()
    return data


async def record_audit_log(
    db: AsyncSession,
    *,
    event_type: str,
    source: str,
    trace_id: str | None = None,
    actor_type: str | None = "system",
    actor_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
    platform: str | None = None,
    account_id: str | None = None,
    sender_phone: str | None = None,
    script_hit_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO audit_logs (
                trace_id, event_type, source, actor_type, actor_id, user_id,
                conversation_id, message_id, platform, account_id, sender_phone,
                script_hit_id, payload
            )
            VALUES (
                :trace_id, :event_type, :source, :actor_type, :actor_id, :user_id,
                :conversation_id, :message_id, :platform, :account_id, :sender_phone,
                :script_hit_id, CAST(:payload AS JSONB)
            )
            """
        ),
        {
            "trace_id": trace_id,
            "event_type": event_type,
            "source": source,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "platform": platform,
            "account_id": account_id,
            "sender_phone": sender_phone,
            "script_hit_id": script_hit_id,
            "payload": _json_payload(payload),
        },
    )


async def get_recent_audit_logs(
    db: AsyncSession,
    *,
    limit: int = RECENT_AUDIT_LIMIT,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, RECENT_AUDIT_LIMIT))
    result = await db.execute(
        text(
            """
            SELECT
                id, trace_id, event_type, source, actor_type, actor_id, user_id,
                conversation_id, message_id, platform, account_id, sender_phone,
                script_hit_id, payload, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"limit": bounded_limit},
    )
    rows: Sequence[Any] = result.mappings().all()
    return [serialize_audit_row(row) for row in rows]
