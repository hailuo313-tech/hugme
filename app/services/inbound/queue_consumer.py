"""Redis Stream inbound_queue consumer for P1-06 and P1-16."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_log_service import record_audit_log


INBOUND_QUEUE_STREAM = "inbound_queue"
DEFAULT_CONSUMER_GROUP = "inbound-consumers"
DEFAULT_CONSUMER_NAME = "eris-api"

InboundHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def normalize_stream_fields(fields: Mapping[Any, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        str(_decode(key)): _decode(value) for key, value in fields.items()
    }
    metadata = normalized.get("metadata")
    if isinstance(metadata, str):
        try:
            normalized["metadata"] = json.loads(metadata)
        except json.JSONDecodeError:
            normalized["metadata"] = {"raw": metadata}
    return normalized


async def ensure_consumer_group(
    redis: Any,
    *,
    stream: str = INBOUND_QUEUE_STREAM,
    group: str = DEFAULT_CONSUMER_GROUP,
) -> None:
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def read_inbound_queue(
    redis: Any,
    *,
    stream: str = INBOUND_QUEUE_STREAM,
    group: str = DEFAULT_CONSUMER_GROUP,
    consumer: str = DEFAULT_CONSUMER_NAME,
    count: int = 10,
    block_ms: int = 1000,
) -> list[tuple[str, dict[str, Any]]]:
    raw = await redis.xreadgroup(
        group,
        consumer,
        {stream: ">"},
        count=count,
        block=block_ms,
    )
    entries: list[tuple[str, dict[str, Any]]] = []
    for raw_stream, raw_messages in raw or []:
        if str(_decode(raw_stream)) != stream:
            continue
        for message_id, fields in raw_messages:
            entries.append((str(_decode(message_id)), normalize_stream_fields(fields)))
    return entries


async def process_inbound_queue_once(
    redis: Any,
    db: AsyncSession,
    *,
    handler: InboundHandler,
    stream: str = INBOUND_QUEUE_STREAM,
    group: str = DEFAULT_CONSUMER_GROUP,
    consumer: str = DEFAULT_CONSUMER_NAME,
    count: int = 10,
    block_ms: int = 1000,
) -> int:
    await ensure_consumer_group(redis, stream=stream, group=group)
    entries = await read_inbound_queue(
        redis,
        stream=stream,
        group=group,
        consumer=consumer,
        count=count,
        block_ms=block_ms,
    )
    processed = 0
    for message_id, fields in entries:
        await handler(fields)
        await record_audit_log(
            db,
            event_type="inbound_queue.consumed",
            source="inbound_queue_consumer",
            trace_id=fields.get("trace_id"),
            user_id=fields.get("external_user_id"),
            platform=fields.get("platform"),
            account_id=fields.get("account_id"),
            sender_phone=fields.get("sender_phone"),
            payload={
                "redis_message_id": message_id,
                "message_type": fields.get("message_type"),
                "metadata": fields.get("metadata") or {},
            },
        )
        commit = getattr(db, "commit", None)
        if commit is not None:
            await commit()
        await redis.xack(stream, group, message_id)
        processed += 1
    return processed
