"""Stage 4 shadow command consumer.

Claims test commands with FOR UPDATE SKIP LOCKED. Shadow mode never connects
Telegram sessions and never sends messages. Production ``all`` does not start
this consumer.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.process_role import is_shadow_runtime


def sql_uuid_or_none(value: Any) -> str | None:
    text_value = "" if value is None else str(value).strip()
    if not text_value:
        return None
    try:
        from uuid import UUID

        return str(UUID(text_value))
    except Exception:
        return None


def is_missing_runtime_schema(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        "undefinedtable" in name
        or "does not exist" in message
        or "runtime_commands" in message
        or "runtime_events" in message
        or "telegram_account_ownership" in message
    )

CLAIM_SQL = """
WITH picked AS (
    SELECT id
    FROM runtime_commands
    WHERE status = 'pending'
      AND available_at <= NOW()
      AND command_type NOT IN (
          'connect_account', 'disconnect_account', 'delete_account', 'sync_account', 'reconnect_account',
          'send_message', 'send_media', 'send_text', 'outbound_message', 'call_start', 'call_outbound',
          'answer_call', 'reject_call', 'hangup_call'
      )
    ORDER BY priority DESC, available_at ASC, created_at ASC
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
)
UPDATE runtime_commands AS c
SET
    status = 'leased',
    lease_owner = :owner,
    lease_until = NOW() + make_interval(secs => :lease_seconds),
    attempts = c.attempts + 1,
    updated_at = NOW()
FROM picked
WHERE c.id = picked.id
RETURNING
    c.id,
    c.command_type,
    c.account_id,
    c.conversation_id,
    c.payload,
    c.generation,
    c.idempotency_key,
    c.attempts,
    c.max_attempts,
    c.trace_id,
    c.status,
    c.lease_owner,
    c.lease_until
"""

RECLAIM_SQL = """
UPDATE runtime_commands
SET
    status = CASE
        WHEN attempts >= max_attempts THEN 'expired'
        ELSE 'pending'
    END,
    lease_owner = NULL,
    lease_until = NULL,
    error = CASE
        WHEN attempts >= max_attempts THEN 'lease_exhausted'
        ELSE error
    END,
    completed_at = CASE
        WHEN attempts >= max_attempts THEN NOW()
        ELSE completed_at
    END,
    updated_at = NOW()
WHERE status = 'leased'
  AND lease_until IS NOT NULL
  AND lease_until < NOW()
RETURNING id, status
"""

FINISH_SQL = """
UPDATE runtime_commands
SET
    status = :status,
    result = CAST(:result AS jsonb),
    error = :error,
    lease_owner = NULL,
    lease_until = NULL,
    completed_at = NOW(),
    updated_at = NOW()
WHERE id = CAST(:command_id AS uuid)
  AND status = 'leased'
  AND lease_owner = :owner
RETURNING id
"""

OWNERSHIP_SQL = """
SELECT owner, generation
FROM telegram_account_ownership
WHERE account_id = CAST(:account_id AS uuid)
"""

EVENT_SQL = """
INSERT INTO runtime_events (
    command_id, account_id, event_type, payload, generation, instance_key, trace_id
) VALUES (
    CAST(:command_id AS uuid),
    CAST(NULLIF(:account_id, '') AS uuid),
    :event_type,
    CAST(:payload AS jsonb),
    :generation,
    :instance_key,
    :trace_id
)
"""

CONNECT_COMMAND_TYPES = frozenset({
    "connect_account",
    "disconnect_account",
    "delete_account",
    "sync_account",
    "reconnect_account",
})
SEND_COMMAND_TYPES = frozenset({
    "send_message",
    "send_media",
    "send_text",
    "outbound_message",
    "call_start",
    "call_outbound",
    "answer_call",
    "reject_call",
    "hangup_call",
})
FORBIDDEN_COMMAND_TYPES = CONNECT_COMMAND_TYPES | SEND_COMMAND_TYPES

_consumer_task: asyncio.Task | None = None
_consumer_stop: asyncio.Event | None = None
_session_factory: Callable | None = None
_schema_missing_until = 0.0


def set_session_factory(factory: Callable | None) -> None:
    global _session_factory
    _session_factory = factory


def reset_shadow_consumer_state() -> None:
    global _consumer_task, _consumer_stop, _schema_missing_until
    _consumer_task = None
    _consumer_stop = None
    _schema_missing_until = 0.0
    set_session_factory(None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return None


def classify_shadow_command(
    command: dict,
    ownership: dict | None = None,
    *,
    now: datetime | None = None,
    shadow_mode: bool = True,
) -> dict:
    """Decide whether a claimed command may be dry-run completed.

    Never performs Telegram connect or send. Used by the shadow consumer only.
    """
    current = now or _utcnow()
    command_type = str(command.get("command_type") or "")
    payload = command.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    if str(command.get("status") or "") == "expired":
        return {"action": "reject", "status": "expired", "reason": "expired"}

    expires_at = payload.get("expires_at")
    if isinstance(expires_at, (int, float)) and current.timestamp() > float(expires_at):
        return {"action": "reject", "status": "expired", "reason": "expired"}

    attempts = int(command.get("attempts") or 0)
    max_attempts = int(command.get("max_attempts") or 3)
    if attempts > max_attempts:
        return {"action": "reject", "status": "expired", "reason": "expired"}

    command_generation = int(command.get("generation") or 0)
    if ownership is not None:
        owner_generation = int(ownership.get("generation") or 0)
        if command_generation < owner_generation:
            return {
                "action": "reject",
                "status": "failed",
                "reason": "stale_generation",
            }

    if shadow_mode and command_type in FORBIDDEN_COMMAND_TYPES:
        kind = "connect" if command_type in CONNECT_COMMAND_TYPES else "send"
        return {
            "action": "reject",
            "status": "failed",
            "reason": f"shadow_forbidden_{kind}",
        }

    return {
        "action": "succeed",
        "status": "succeeded",
        "reason": "shadow_dry_run",
    }


class InMemoryCommandStore:
    """Lease/claim semantics for tests. Serializes claims so one row cannot be
    leased twice at the same time.
    """

    def __init__(self) -> None:
        self.commands: dict[str, dict] = {}
        self.ownership: dict[str, dict] = {}
        self.events: list[dict] = []
        self._lock = asyncio.Lock()

    async def insert_command(self, command: dict) -> dict:
        async with self._lock:
            key = str(command["idempotency_key"])
            for existing in self.commands.values():
                if existing["idempotency_key"] == key:
                    return dict(existing)
            row = {
                "id": str(command.get("id") or uuid4()),
                "command_type": command["command_type"],
                "account_id": command.get("account_id"),
                "conversation_id": command.get("conversation_id"),
                "payload": dict(command.get("payload") or {}),
                "status": command.get("status") or "pending",
                "priority": int(command.get("priority") or 0),
                "generation": int(command.get("generation") or 0),
                "idempotency_key": key,
                "lease_owner": None,
                "lease_until": None,
                "available_at": command.get("available_at") or _utcnow(),
                "attempts": int(command.get("attempts") or 0),
                "max_attempts": int(command.get("max_attempts") or 3),
                "result": None,
                "error": None,
                "trace_id": command.get("trace_id"),
                "created_at": command.get("created_at") or _utcnow(),
                "completed_at": None,
            }
            self.commands[row["id"]] = row
            return dict(row)

    async def reclaim_expired(self, *, now: datetime | None = None) -> list[dict]:
        current = now or _utcnow()
        async with self._lock:
            changed: list[dict] = []
            for row in self.commands.values():
                if row["status"] != "leased":
                    continue
                until = _as_dt(row.get("lease_until"))
                if until is None or until >= current:
                    continue
                if int(row["attempts"]) >= int(row["max_attempts"]):
                    row["status"] = "expired"
                    row["error"] = "lease_exhausted"
                    row["completed_at"] = current
                else:
                    row["status"] = "pending"
                row["lease_owner"] = None
                row["lease_until"] = None
                changed.append({"id": row["id"], "status": row["status"]})
            return changed

    async def claim(
        self,
        owner: str,
        *,
        limit: int = 10,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> list[dict]:
        current = now or _utcnow()
        async with self._lock:
            eligible = [
                row
                for row in self.commands.values()
                if row["status"] == "pending" and row["available_at"] <= current
            ]
            eligible.sort(
                key=lambda row: (-row["priority"], row["available_at"], row["created_at"])
            )
            claimed: list[dict] = []
            for row in eligible[:limit]:
                row["status"] = "leased"
                row["lease_owner"] = owner
                row["lease_until"] = current + timedelta(seconds=lease_seconds)
                row["attempts"] = int(row["attempts"]) + 1
                claimed.append(dict(row))
            return claimed

    async def get_ownership(self, account_id: str | None) -> dict | None:
        if not account_id:
            return None
        return self.ownership.get(str(account_id))

    async def finish(
        self,
        command_id: str,
        *,
        owner: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = now or _utcnow()
        async with self._lock:
            row = self.commands.get(str(command_id))
            if row is None:
                return False
            if row["status"] != "leased" or row["lease_owner"] != owner:
                return False
            row["status"] = status
            row["result"] = result
            row["error"] = error
            row["lease_owner"] = None
            row["lease_until"] = None
            row["completed_at"] = current
            return True

    async def append_event(self, event: dict) -> None:
        self.events.append(dict(event))


class PostgresCommandStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reclaim_expired(self, *, now: datetime | None = None) -> list[dict]:
        result = await self.session.execute(text(RECLAIM_SQL))
        rows = [dict(row._mapping) for row in result]
        await self.session.commit()
        return rows

    async def claim(
        self,
        owner: str,
        *,
        limit: int = 10,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> list[dict]:
        result = await self.session.execute(
            text(CLAIM_SQL),
            {"owner": owner, "limit": int(limit), "lease_seconds": int(lease_seconds)},
        )
        rows = []
        for row in result:
            mapping = dict(row._mapping)
            if mapping.get("id") is not None:
                mapping["id"] = str(mapping["id"])
            if mapping.get("account_id") is not None:
                mapping["account_id"] = str(mapping["account_id"])
            rows.append(mapping)
        await self.session.commit()
        return rows

    async def get_ownership(self, account_id: str | None) -> dict | None:
        account_uuid = sql_uuid_or_none(account_id)
        if not account_uuid:
            return None
        result = await self.session.execute(
            text(OWNERSHIP_SQL),
            {"account_id": account_uuid},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def finish(
        self,
        command_id: str,
        *,
        owner: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        outcome = await self.session.execute(
            text(FINISH_SQL),
            {
                "command_id": str(command_id),
                "owner": owner,
                "status": status,
                "result": json.dumps(result or {}),
                "error": error,
            },
        )
        updated = outcome.first() is not None
        await self.session.commit()
        return updated

    async def append_event(self, event: dict) -> None:
        try:
            await self.session.execute(
                text(EVENT_SQL),
                {
                    "command_id": event.get("command_id"),
                    "account_id": sql_uuid_or_none(event.get("account_id")) or "",
                    "event_type": event.get("event_type"),
                    "payload": json.dumps(event.get("payload") or {}),
                    "generation": event.get("generation"),
                    "instance_key": event.get("instance_key"),
                    "trace_id": event.get("trace_id"),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()


async def process_claimed_commands(
    store: InMemoryCommandStore | PostgresCommandStore,
    commands: list[dict],
    *,
    owner: str,
    shadow_mode: bool = True,
    now: datetime | None = None,
) -> dict:
    stats = {
        "claimed": len(commands),
        "succeeded": 0,
        "rejected": 0,
        "forbidden": 0,
        "stale": 0,
        "expired": 0,
    }
    current = now or _utcnow()
    for command in commands:
        ownership = await store.get_ownership(command.get("account_id"))
        decision = classify_shadow_command(
            command,
            ownership,
            now=current,
            shadow_mode=shadow_mode,
        )
        result = {
            "shadow": True,
            "executed": False,
            "reason": decision["reason"],
            "command_type": command.get("command_type"),
        }
        finished = await store.finish(
            str(command["id"]),
            owner=owner,
            status=decision["status"],
            result=result,
            error=None if decision["action"] == "succeed" else decision["reason"],
            now=current,
        )
        await store.append_event(
            {
                "command_id": str(command["id"]),
                "account_id": command.get("account_id"),
                "event_type": f"shadow.{decision['reason']}",
                "payload": result,
                "generation": command.get("generation"),
                "instance_key": owner,
                "trace_id": command.get("trace_id"),
            }
        )
        if not finished:
            continue
        if decision["action"] == "succeed":
            stats["succeeded"] += 1
        else:
            stats["rejected"] += 1
            if decision["reason"].startswith("shadow_forbidden"):
                stats["forbidden"] += 1
            elif decision["reason"] == "stale_generation":
                stats["stale"] += 1
            elif decision["reason"] == "expired":
                stats["expired"] += 1
    return stats


async def run_shadow_consumer_once(
    store: InMemoryCommandStore | PostgresCommandStore,
    *,
    owner: str,
    limit: int = 10,
    lease_seconds: int = 30,
    shadow_mode: bool = True,
    now: datetime | None = None,
) -> dict:
    reclaimed = await store.reclaim_expired(now=now)
    claimed = await store.claim(
        owner,
        limit=limit,
        lease_seconds=lease_seconds,
        now=now,
    )
    processed = await process_claimed_commands(
        store,
        claimed,
        owner=owner,
        shadow_mode=shadow_mode,
        now=now,
    )
    return {"reclaimed": len(reclaimed), **processed}


async def _postgres_tick(
    *,
    owner: str,
    limit: int,
    lease_seconds: int,
) -> dict:
    global _schema_missing_until
    now = time.time()
    if now < _schema_missing_until:
        return {"claimed": 0, "skipped": "schema_missing"}
    factory = _session_factory
    if factory is None:
        from core.database import AsyncSessionLocal

        factory = AsyncSessionLocal
    try:
        async with factory() as session:
            store = PostgresCommandStore(session)
            return await run_shadow_consumer_once(
                store,
                owner=owner,
                limit=limit,
                lease_seconds=lease_seconds,
                shadow_mode=True,
            )
    except Exception as exc:
        if is_missing_runtime_schema(exc):
            _schema_missing_until = now + 30
            logger.bind(
                component="runtime",
                error_type=type(exc).__name__,
            ).warning("runtime_shadow.consumer.schema_missing")
            return {"claimed": 0, "skipped": "schema_missing"}
        raise


async def _consumer_loop(
    *,
    owner: str,
    poll_seconds: float,
    limit: int,
    lease_seconds: int,
) -> None:
    assert _consumer_stop is not None
    while not _consumer_stop.is_set():
        try:
            stats = await _postgres_tick(
                owner=owner,
                limit=limit,
                lease_seconds=lease_seconds,
            )
            if stats.get("skipped") == "schema_missing":
                pass
            elif stats.get("claimed"):
                logger.bind(component="runtime", **stats).info(
                    "runtime_shadow.consumer.tick"
                )
        except Exception as exc:
            logger.bind(
                component="runtime",
                error_type=type(exc).__name__,
            ).warning("runtime_shadow.consumer.tick_failed")
        try:
            await asyncio.wait_for(_consumer_stop.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            continue


async def start_shadow_consumer(
    *,
    owner: str | None = None,
    poll_seconds: float = 2.0,
    limit: int = 10,
    lease_seconds: int = 30,
) -> None:
    global _consumer_task, _consumer_stop
    if not is_shadow_runtime():
        logger.bind(component="runtime").info("runtime_shadow.consumer.skipped")
        return
    await stop_shadow_consumer()
    from services.runtime_shadow_state import get_instance_key

    lease_owner = owner or f"shadow:{get_instance_key()}"
    _consumer_stop = asyncio.Event()
    _consumer_task = asyncio.create_task(
        _consumer_loop(
            owner=lease_owner,
            poll_seconds=max(0.2, float(poll_seconds)),
            limit=max(1, int(limit)),
            lease_seconds=max(5, int(lease_seconds)),
        )
    )
    logger.bind(
        component="runtime",
        lease_owner=lease_owner,
    ).info("runtime_shadow.consumer.started")


async def stop_shadow_consumer() -> None:
    global _consumer_task, _consumer_stop
    if _consumer_stop is not None:
        _consumer_stop.set()
    task = _consumer_task
    _consumer_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _consumer_stop = None
    if task is not None:
        logger.bind(component="runtime").info("runtime_shadow.consumer.stopped")
