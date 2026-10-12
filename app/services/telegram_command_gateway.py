"""Stage 6 dual-channel Telegram command gateway.

Legacy accounts (default, including missing ownership) execute in-process.
Runtime accounts are enqueued and never reported as already sent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from loguru import logger
from sqlalchemy import text

from core.process_role import is_shadow_runtime, owns_telegram_runtime
from services.runtime_ownership import (
    claim_account_for_runtime,
    get_account_ownership,
    is_missing_runtime_schema,
    looks_like_uuid,
    sql_uuid_or_none,
)
from services.runtime_shadow_consumer import FORBIDDEN_COMMAND_TYPES, InMemoryCommandStore

LegacyFn = Callable[[], Awaitable[Any]]

INTERACTIVE_COMMAND_TYPES = frozenset(
    {
        "delete_account",
        "disconnect_account",
        "answer_call",
        "reject_call",
        "hangup_call",
    }
)


def priority_for_command(command_type: str, explicit: int | None = None) -> int:
    if explicit is not None:
        return int(explicit)
    if command_type in INTERACTIVE_COMMAND_TYPES:
        return 100
    return 0

_command_store: InMemoryCommandStore | None = None


def set_gateway_command_store(store: InMemoryCommandStore | None) -> None:
    global _command_store
    _command_store = store


def reset_gateway_runtime_state() -> None:
    set_gateway_command_store(None)


@dataclass
class GatewayResult:
    executed: bool
    owner: str
    status: str
    value: Any = None
    command_id: str | None = None
    reason: str | None = None
    generation: int = 0

    @property
    def accepted_not_sent(self) -> bool:
        return (not self.executed) and self.status in {"pending", "leased", "accepted"}


async def enqueue_runtime_command(
    *,
    command_type: str,
    account_id: str | None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    generation: int = 0,
    trace_id: str | None = None,
    priority: int = 0,
) -> str:
    key = idempotency_key or f"{command_type}:{account_id or 'none'}:{uuid4().hex}"
    if _command_store is not None:
        row = await _command_store.insert_command(
            {
                "command_type": command_type,
                "account_id": account_id,
                "payload": payload or {},
                "idempotency_key": key,
                "generation": generation,
                "priority": priority,
                "trace_id": trace_id,
            }
        )
        return str(row["id"])
    from core.database import AsyncSessionLocal

    account_uuid = sql_uuid_or_none(account_id) or ""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    """
                    INSERT INTO runtime_commands (
                        command_type, account_id, payload, status, priority, generation,
                        idempotency_key, available_at, created_by, trace_id
                    ) VALUES (
                        :command_type,
                        CAST(NULLIF(:account_id, '') AS uuid),
                        CAST(:payload AS jsonb),
                        'pending',
                        :priority,
                        :generation,
                        :idempotency_key,
                        NOW(),
                        'gateway',
                        :trace_id
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET updated_at = runtime_commands.updated_at
                    RETURNING id::text
                    """
                ),
                {
                    "command_type": command_type,
                    "account_id": account_uuid,
                    "payload": json.dumps(payload or {}),
                    "priority": int(priority),
                    "generation": int(generation),
                    "idempotency_key": key,
                    "trace_id": trace_id,
                },
            )
            row = result.first()
            await db.commit()
            return str(row[0]) if row else key
    except Exception as exc:
        if is_missing_runtime_schema(exc):
            raise RuntimeError("runtime_schema_missing") from exc
        raise


async def _enqueue_owned_command(
    *,
    command_type: str,
    account_id: str | None,
    payload: dict | None,
    idempotency_key: str | None,
    generation: int,
    trace_id: str | None,
    priority: int = 0,
) -> GatewayResult:
    try:
        command_id = await enqueue_runtime_command(
            command_type=command_type,
            account_id=account_id,
            payload=payload,
            idempotency_key=idempotency_key,
            generation=generation,
            trace_id=trace_id,
            priority=priority,
        )
    except Exception as exc:
        reason = (
            "runtime_schema_missing"
            if is_missing_runtime_schema(exc) or "runtime_schema_missing" in str(exc)
            else "runtime_enqueue_failed"
        )
        logger.bind(
            component="runtime",
            command_type=command_type,
            account_id=account_id,
            error_type=type(exc).__name__,
        ).warning("telegram_gateway.enqueue_failed")
        return GatewayResult(
            executed=False,
            owner="runtime",
            status="failed",
            reason=reason,
            generation=generation,
        )
    logger.bind(
        component="runtime",
        command_type=command_type,
        account_id=account_id,
        command_id=command_id,
    ).info("telegram_gateway.enqueued")
    return GatewayResult(
        executed=False,
        owner="runtime",
        status="accepted",
        command_id=command_id,
        reason="queued_for_runtime",
        generation=generation,
    )


async def wait_for_runtime_command(
    command_id: str,
    *,
    timeout_seconds: float = 45,
    poll_seconds: float = 0.15,
) -> GatewayResult:
    """Block until a queued runtime command finishes or times out."""
    import asyncio

    from core.database import AsyncSessionLocal

    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    interval = min(0.15, max(0.04, float(poll_seconds)))
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT status, result, error
                        FROM runtime_commands
                        WHERE id = CAST(:command_id AS uuid)
                        """
                    ),
                    {"command_id": command_id},
                )
            ).mappings().one_or_none()
        if row and str(row["status"] or "") in {"succeeded", "failed", "cancelled", "expired"}:
            result = row["result"] if isinstance(row["result"], dict) else {}
            executed = bool(result.get("executed")) if result else str(row["status"]) == "succeeded"
            return GatewayResult(
                executed=executed,
                owner="runtime",
                status=str(row["status"]),
                value=result,
                command_id=command_id,
                reason=str(row["error"] or result.get("reason") or row["status"]),
            )
        await asyncio.sleep(interval)
    logger.bind(component="runtime", command_id=command_id).warning("telegram_gateway.wait_timeout")
    return GatewayResult(
        executed=False,
        owner="runtime",
        status="failed",
        command_id=command_id,
        reason="runtime_command_timeout",
    )


async def submit_telegram_command(
    *,
    command_type: str,
    account_id: str | None,
    legacy_execute: LegacyFn,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    priority: int | None = None,
) -> GatewayResult:
    resolved_priority = priority_for_command(command_type, priority)
    ownership = await get_account_ownership(account_id)
    if ownership.is_runtime:
        return await _enqueue_owned_command(
            command_type=command_type,
            account_id=account_id,
            payload=payload,
            idempotency_key=idempotency_key,
            generation=ownership.generation,
            trace_id=trace_id,
            priority=resolved_priority,
        )

    if is_shadow_runtime() and command_type in FORBIDDEN_COMMAND_TYPES:
        return GatewayResult(
            executed=False,
            owner="legacy",
            status="failed",
            reason="shadow_forbidden",
            generation=ownership.generation,
        )

    if not owns_telegram_runtime():
        if account_id and looks_like_uuid(str(account_id)):
            ownership = await claim_account_for_runtime(str(account_id))
            if ownership.is_runtime:
                return await _enqueue_owned_command(
                    command_type=command_type,
                    account_id=account_id,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    generation=ownership.generation,
                    trace_id=trace_id,
                    priority=resolved_priority,
                )
        return GatewayResult(
            executed=False,
            owner="legacy",
            status="failed",
            reason="telegram_control_not_on_this_process",
            generation=ownership.generation,
        )

    value = await legacy_execute()
    return GatewayResult(
        executed=True,
        owner="legacy",
        status="succeeded",
        value=value,
        generation=ownership.generation,
    )
