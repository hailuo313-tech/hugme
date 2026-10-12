"""Real account switcher for Step C.

plan_account_switch only plans. This module is the only writer of owner=runtime.
Default is dry-run. execute=True is required to change production state.
Canary stays off until Step D; missing any gate refuses the write.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.runtime_canary import plan_account_switch, should_abort_canary
from services.runtime_ownership import (
    load_switch_probes,
    reset_ownership_runtime_state,
)
from services.telegram_command_gateway import enqueue_runtime_command


DRAIN_TIMEOUT_SECONDS = 30
CONNECT_WAIT_SECONDS = 45
SWITCH_STEPS = (
    "canary_and_red_lines",
    "switch_admission",
    "drain_sending",
    "legacy_disconnect",
    "write_runtime_ownership",
    "runtime_connect",
    "verify_messages",
)


def _canary_enabled(explicit: bool | None, *, allow_override: bool) -> bool:
    if allow_override and explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "RUNTIME_CANARY_ENABLED", False))


async def _count_open_work(account_id: str) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        sending = int(
            (
                await db.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM message_schedules
                             WHERE account_id::text = :account_id AND status = 'sending')
                        + (SELECT count(*) FROM fixed_auto_reply_jobs
                             WHERE account_id = CAST(:account_id AS uuid)
                               AND status IN ('sending', 'claimed'))
                        + (SELECT count(*) FROM call_broadcast_jobs
                             WHERE account_id = CAST(:account_id AS uuid)
                               AND status IN ('queued', 'claimed'))
                        """
                    ),
                    {"account_id": account_id},
                )
            ).scalar()
            or 0
        )
        queued = int(
            (
                await db.execute(
                    text(
                        """
                        SELECT count(*) FROM runtime_commands
                        WHERE account_id = CAST(:account_id AS uuid)
                          AND status IN ('pending', 'leased')
                        """
                    ),
                    {"account_id": account_id},
                )
            ).scalar()
            or 0
        )
    return {"sending": sending, "queued_commands": queued}


async def _write_runtime_ownership(account_id: str, generation: int, switch_status: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO telegram_account_ownership (account_id, owner, generation, switch_status)
                VALUES (CAST(:account_id AS uuid), 'runtime', :generation, :switch_status)
                ON CONFLICT (account_id) DO UPDATE
                SET owner = 'runtime',
                    generation = :generation,
                    switch_status = :switch_status,
                    updated_at = NOW()
                """
            ),
            {
                "account_id": account_id,
                "generation": int(generation),
                "switch_status": switch_status,
            },
        )
        await db.commit()
    reset_ownership_runtime_state()


async def rollback_account_to_legacy(account_id: str) -> None:
    """Delete the ownership row so the account returns to implicit legacy."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM telegram_account_ownership WHERE account_id = CAST(:account_id AS uuid)"
            ),
            {"account_id": account_id},
        )
        await db.commit()
    reset_ownership_runtime_state()


def _legacy_api_bases() -> list[str]:
    explicit = (os.environ.get("LEGACY_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return [explicit]
    return ["http://127.0.0.1:8000", "http://api:8000"]


def _http_json(method: str, url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


async def release_legacy_session(account_id: str) -> dict:
    """Drop the session in the process that still holds it.

    docker exec cannot see uvicorn memory, so HTTP to the live API is the
    Legacy release path. Must be called while owner is still legacy, otherwise
    the gateway enqueues disconnect to Runtime and the API client stays up.
    """
    local = {"had_client": False, "released_local": False}
    try:
        from services.telegram_account_manager import telegram_account_manager

        client = await telegram_account_manager.get_client(UUID(account_id))
        if client is not None:
            local["had_client"] = True
            await telegram_account_manager.disconnect_account(UUID(account_id))
            local["released_local"] = True
            still = await telegram_account_manager.get_client(UUID(account_id))
            if still is None:
                return {"ok": True, "via": "local_manager", **local}
    except Exception as exc:
        local["local_error"] = type(exc).__name__

    last_error = "legacy_api_unreachable"
    for base in _legacy_api_bases():
        url = f"{base}/api/v1/telegram/accounts/{account_id}/disconnect"
        try:
            payload = _http_json("POST", url)
            if payload.get("status") in {"disconnected", "accepted"}:
                return {"ok": True, "via": base, "http": payload, **local}
            last_error = str(payload)
        except Exception as exc:
            last_error = type(exc).__name__
    return {"ok": False, "reason": last_error, **local}


async def reconnect_legacy_session(account_id: str) -> dict:
    """Ask the live Legacy API (8000) to take the session back after a failed switch."""
    last_error = "legacy_api_unreachable"
    for base in _legacy_api_bases():
        url = f"{base}/api/v1/telegram/accounts/{account_id}/connect"
        try:
            payload = _http_json("POST", url, timeout=60)
            if payload.get("status") in {"connected", "accepted"}:
                return {"ok": True, "via": base, "http": payload}
            last_error = str(payload)
        except Exception as exc:
            last_error = type(exc).__name__
    return {"ok": False, "reason": last_error}


async def _wait_drain(account_id: str, timeout: int = DRAIN_TIMEOUT_SECONDS) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = await _count_open_work(account_id)
        if last["sending"] == 0 and last["queued_commands"] == 0:
            return {"ok": True, **last}
        await asyncio.sleep(1)
    return {"ok": False, "reason": "drain_timeout", **last}


async def apply_account_switch(
    account_id: str,
    *,
    dry_run: bool = True,
    execute: bool = False,
    canary_enabled: bool | None = None,
    allow_canary_override: bool = False,
    metrics: dict | None = None,
    verify_messages: bool = False,
) -> dict:
    """Switch one account to Runtime. Refuses unless every gate passes.

    dry_run (default) never writes ownership, never disconnects, never connects.
    execute=True is the only production mutation path and still requires the
    process Canary flag, unless an explicit override is used in tests.
    """
    if execute and dry_run:
        return {"ok": False, "reasons": ["dry_run_and_execute"], "steps": []}
    if execute and not dry_run and verify_messages is False:
        # Step 7 stays optional until D; C/D callers opt in.
        pass

    enabled = _canary_enabled(canary_enabled, allow_override=allow_canary_override)
    planned = plan_account_switch({"healthy": True}, canary_enabled=enabled)
    if planned.get("reasons") == ["canary_disabled"]:
        return {
            "ok": False,
            "reasons": ["canary_disabled"],
            "steps": ["canary_and_red_lines"],
            "wrote_ownership": False,
        }

    abort = should_abort_canary(metrics)
    if abort:
        return {
            "ok": False,
            "reasons": [abort],
            "steps": ["canary_and_red_lines"],
            "wrote_ownership": False,
        }

    async with AsyncSessionLocal() as db:
        probes = await load_switch_probes(db, account_id)
    admission = plan_account_switch({**probes, "metrics": metrics or {}}, canary_enabled=True)
    if not admission.get("ok"):
        return {
            "ok": False,
            "reasons": admission.get("reasons") or ["admission_failed"],
            "probes": probes,
            "steps": ["canary_and_red_lines", "switch_admission"],
            "wrote_ownership": False,
        }

    work = await _count_open_work(account_id)
    result: dict[str, Any] = {
        "ok": True,
        "account_id": account_id,
        "dry_run": dry_run and not execute,
        "execute": bool(execute) and not dry_run,
        "reasons": [],
        "probes": probes,
        "open_work": work,
        "next_generation": admission.get("next_generation"),
        "steps": list(SWITCH_STEPS),
        "wrote_ownership": False,
    }
    if result["dry_run"]:
        result["would"] = {
            "drain": True,
            "legacy_disconnect": True,
            "write_owner_runtime": True,
            "enqueue_connect": True,
            "verify_messages": bool(verify_messages),
        }
        return result

    drain = await _wait_drain(account_id)
    if not drain.get("ok"):
        result.update({"ok": False, "reasons": ["drain_timeout"], "drain": drain})
        return result

    async with AsyncSessionLocal() as db:
        probes = await load_switch_probes(db, account_id)
    admission = plan_account_switch({**probes, "metrics": metrics or {}}, canary_enabled=True)
    if not admission.get("ok"):
        result.update(
            {
                "ok": False,
                "reasons": admission.get("reasons") or ["admission_failed_after_drain"],
                "probes": probes,
            }
        )
        return result

    released = await release_legacy_session(account_id)
    if not released.get("ok"):
        result.update({"ok": False, "reasons": ["legacy_disconnect_failed"], "release": released})
        return result

    generation = int(admission.get("next_generation") or 2)
    try:
        await _write_runtime_ownership(account_id, generation, "switching")
        result["wrote_ownership"] = True
        # Runtime process caches missing/legacy ownership for 5s; enqueue after TTL.
        await asyncio.sleep(6)
        command_id = await enqueue_runtime_command(
            command_type="connect_account",
            account_id=account_id,
            payload={"switch": True},
            generation=generation,
            idempotency_key=f"switch-connect:{account_id}:{generation}:{int(time.time())}",
        )
        result["connect_command_id"] = command_id
        connected = await _wait_connect_command(command_id)
        if not connected.get("ok"):
            await rollback_account_to_legacy(account_id)
            result.update(
                {
                    "ok": False,
                    "reasons": ["runtime_connect_failed"],
                    "connect": connected,
                    "wrote_ownership": False,
                    "rolled_back": True,
                    "legacy_reconnect": await reconnect_legacy_session(account_id),
                }
            )
            return result
        await _write_runtime_ownership(account_id, generation, "stable")
        result["connect"] = connected
        if verify_messages:
            result["verify"] = {
                "ok": False,
                "reason": "verify_deferred_to_step_d",
            }
        return result
    except Exception as exc:
        logger.bind(account_id=account_id, error_type=type(exc).__name__).warning(
            "runtime_switch.apply_failed"
        )
        await rollback_account_to_legacy(account_id)
        result.update(
            {
                "ok": False,
                "reasons": [type(exc).__name__],
                "wrote_ownership": False,
                "rolled_back": True,
                "legacy_reconnect": await reconnect_legacy_session(account_id),
            }
        )
        return result


async def _wait_connect_command(command_id: str, timeout: int = CONNECT_WAIT_SECONDS) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
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
            ).mappings().first()
        last = dict(row) if row else {}
        status = str(last.get("status") or "")
        if status == "succeeded":
            return {"ok": True, **last}
        if status in {"failed", "expired"}:
            return {"ok": False, **last}
        await asyncio.sleep(1)
    return {"ok": False, "reason": "connect_timeout", **last}
