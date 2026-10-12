"""Stage 3 shadow dual-write for runtime status.

Memory / current process state remains the source of truth for routing.
Redis holds a comparison copy only. Redis failures never raise to callers.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from typing import Callable, Iterable

from loguru import logger

ACCOUNT_KEY_PREFIX = "eris:rt:shadow:account:"
HEARTBEAT_KEY_PREFIX = "eris:rt:shadow:heartbeat:"
ACCOUNT_TTL_SECONDS = 45
HEARTBEAT_TTL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10
MAX_STATUS_LAG_SECONDS = 15
CIRCUIT_FAIL_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 15
APP_VERSION = "0.1.0"

_redis_factory: Callable | None = None
_fail_count = 0
_circuit_until = 0.0
_instance_key = ""
_heartbeat_task: asyncio.Task | None = None
_heartbeat_stop: asyncio.Event | None = None


def set_redis_factory(factory: Callable | None) -> None:
    global _redis_factory
    _redis_factory = factory


def reset_shadow_runtime_state() -> None:
    global _fail_count, _circuit_until, _instance_key, _heartbeat_task, _heartbeat_stop
    _fail_count = 0
    _circuit_until = 0.0
    _instance_key = ""
    _heartbeat_task = None
    _heartbeat_stop = None
    set_redis_factory(None)


def get_instance_key() -> str:
    global _instance_key
    if not _instance_key:
        _instance_key = (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
    return _instance_key


def account_shadow_key(account_id: str) -> str:
    return f"{ACCOUNT_KEY_PREFIX}{account_id}"


def heartbeat_shadow_key(instance_key: str | None = None) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}{instance_key or get_instance_key()}"


def _circuit_open(now: float | None = None) -> bool:
    return (now or time.time()) < _circuit_until


def _note_failure() -> None:
    global _fail_count, _circuit_until
    _fail_count += 1
    if _fail_count >= CIRCUIT_FAIL_THRESHOLD:
        _circuit_until = time.time() + CIRCUIT_COOLDOWN_SECONDS


def _note_success() -> None:
    global _fail_count, _circuit_until
    _fail_count = 0
    _circuit_until = 0.0


async def _redis():
    factory = _redis_factory
    if factory is None:
        from core.redis import get_redis

        factory = get_redis
    return await factory()


def compare_account_shadow(
    memory_status: str,
    shadow_payload: dict | None,
    *,
    now: float | None = None,
    max_lag_s: float = MAX_STATUS_LAG_SECONDS,
) -> dict:
    current = now if now is not None else time.time()
    if shadow_payload is None:
        return {"match": False, "reason": "shadow_missing", "lag_s": None}
    lag = current - float(shadow_payload.get("ts") or 0)
    if str(shadow_payload.get("status") or "") != str(memory_status):
        return {
            "match": False,
            "reason": "status_mismatch",
            "lag_s": round(lag, 3),
            "memory": memory_status,
            "shadow": shadow_payload.get("status"),
        }
    if lag > max_lag_s:
        return {"match": False, "reason": "stale", "lag_s": round(lag, 3)}
    return {"match": True, "reason": "ok", "lag_s": round(lag, 3)}


def compare_snapshots(
    memory_rows: Iterable[tuple[str, str]],
    shadow_by_account: dict[str, dict],
    *,
    now: float | None = None,
    max_lag_s: float = MAX_STATUS_LAG_SECONDS,
) -> dict:
    matches = 0
    mismatches: list[dict] = []
    seen = set()
    for account_id, status in memory_rows:
        seen.add(account_id)
        result = compare_account_shadow(
            status,
            shadow_by_account.get(account_id),
            now=now,
            max_lag_s=max_lag_s,
        )
        if result["match"]:
            matches += 1
        else:
            mismatches.append({"account_id": account_id, **result})
    extra_shadow = sorted(set(shadow_by_account) - seen)
    return {
        "matches": matches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "extra_shadow": extra_shadow,
        "diff_count": len(mismatches) + len(extra_shadow),
    }


async def shadow_account_status(account_id: str, status: str) -> bool:
    if _circuit_open():
        return False
    payload = json.dumps(
        {
            "status": status,
            "source": "memory",
            "ts": time.time(),
        },
        separators=(",", ":"),
    )
    try:
        redis = await _redis()
        await asyncio.wait_for(
            redis.set(account_shadow_key(str(account_id)), payload, ex=ACCOUNT_TTL_SECONDS),
            timeout=0.15,
        )
        _note_success()
        return True
    except Exception as exc:
        _note_failure()
        logger.bind(
            component="runtime",
            account_id=str(account_id),
            error_type=type(exc).__name__,
        ).warning("runtime_shadow.account.write_failed")
        return False


async def shadow_runtime_heartbeat(
    *,
    process_role: str,
    version: str = APP_VERSION,
    runtime_ready: bool = False,
) -> bool:
    if _circuit_open():
        return False
    payload = json.dumps(
        {
            "process_role": process_role,
            "version": version,
            "runtime_ready": bool(runtime_ready),
            "ts": time.time(),
        },
        separators=(",", ":"),
    )
    try:
        redis = await _redis()
        await asyncio.wait_for(
            redis.set(heartbeat_shadow_key(), payload, ex=HEARTBEAT_TTL_SECONDS),
            timeout=0.15,
        )
        _note_success()
        return True
    except Exception as exc:
        _note_failure()
        logger.bind(
            component="runtime",
            error_type=type(exc).__name__,
        ).warning("runtime_shadow.heartbeat.write_failed")
        return False


async def read_shadow_account_status(account_id: str) -> dict | None:
    try:
        redis = await _redis()
        raw = await asyncio.wait_for(redis.get(account_shadow_key(str(account_id))), timeout=0.15)
        if not raw:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def shadow_payload_is_live_connected(payload: dict | None, *, now: float | None = None) -> bool:
    """True when Runtime recently advertised this account as connected."""
    if not isinstance(payload, dict):
        return False
    if str(payload.get("status") or "") != "connected":
        return False
    current = now if now is not None else time.time()
    try:
        ts = float(payload.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return (current - ts) <= float(ACCOUNT_TTL_SECONDS)


async def read_all_shadow_account_statuses() -> dict[str, dict]:
    """Read every live account shadow key. Used by API processes with no local clients."""
    out: dict[str, dict] = {}
    try:
        redis = await _redis()
        keys: list = []
        async for key in redis.scan_iter(match=f"{ACCOUNT_KEY_PREFIX}*", count=200):
            keys.append(key)
        if not keys:
            return out
        values = await asyncio.wait_for(redis.mget(keys), timeout=1.5)
    except Exception:
        return out
    now = time.time()
    for key, raw in zip(keys, values or []):
        if not raw:
            continue
        key_s = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
        account_id = key_s[len(ACCOUNT_KEY_PREFIX) :]
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and shadow_payload_is_live_connected(parsed, now=now):
            out[account_id] = parsed
    return out


async def read_shadow_heartbeat() -> dict | None:
    try:
        redis = await _redis()
        raw = await asyncio.wait_for(redis.get(heartbeat_shadow_key()), timeout=0.15)
        if not raw:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def schedule_shadow_account_status(account_id: str, status: str) -> None:
    """Fire-and-forget shadow write. Memory/DB update must already have succeeded."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(shadow_account_status(str(account_id), str(status)))


async def _heartbeat_loop(
    *,
    process_role: str,
    version: str,
    runtime_ready_getter: Callable[[], bool],
    account_snapshot_getter: Callable[[], list[tuple[str, str]]] | None,
) -> None:
    assert _heartbeat_stop is not None
    while not _heartbeat_stop.is_set():
        try:
            await shadow_runtime_heartbeat(
                process_role=process_role,
                version=version,
                runtime_ready=bool(runtime_ready_getter()),
            )
            if account_snapshot_getter is not None:
                memory_rows = list(account_snapshot_getter())
                if memory_rows:
                    # Refresh the complete snapshot in one Redis round trip.
                    # Sequential SET/GET calls for hundreds of accounts can
                    # exceed the 45-second TTL and make the admin UI oscillate
                    # between a partial count and zero.
                    redis = await _redis()
                    snapshot_ts = time.time()
                    pipe = redis.pipeline(transaction=False)
                    for account_id, status in memory_rows:
                        payload = json.dumps(
                            {
                                "status": status,
                                "source": "memory",
                                "ts": snapshot_ts,
                            },
                            separators=(",", ":"),
                        )
                        pipe.set(
                            account_shadow_key(str(account_id)),
                            payload,
                            ex=ACCOUNT_TTL_SECONDS,
                        )
                    await asyncio.wait_for(pipe.execute(), timeout=2.0)
                    _note_success()
                shadow_by_account = await read_all_shadow_account_statuses()
                diff = compare_snapshots(memory_rows, shadow_by_account)
                if diff["diff_count"]:
                    logger.bind(
                        component="runtime",
                        matches=diff["matches"],
                        mismatch_count=diff["mismatch_count"],
                        extra_shadow=len(diff["extra_shadow"]),
                        diff_count=diff["diff_count"],
                    ).warning("runtime_shadow.compare.diff")
                else:
                    logger.bind(
                        component="runtime",
                        matches=diff["matches"],
                    ).debug("runtime_shadow.compare.ok")
        except Exception as exc:
            logger.bind(
                component="runtime",
                error_type=type(exc).__name__,
            ).warning("runtime_shadow.heartbeat.loop_failed")
        try:
            await asyncio.wait_for(
                _heartbeat_stop.wait(),
                timeout=HEARTBEAT_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            continue


async def start_shadow_heartbeat(
    *,
    process_role: str,
    version: str = APP_VERSION,
    runtime_ready_getter: Callable[[], bool] | None = None,
    account_snapshot_getter: Callable[[], list[tuple[str, str]]] | None = None,
) -> None:
    global _heartbeat_task, _heartbeat_stop
    await stop_shadow_heartbeat()
    _heartbeat_stop = asyncio.Event()
    ready = runtime_ready_getter or (lambda: False)
    _heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            process_role=process_role,
            version=version,
            runtime_ready_getter=ready,
            account_snapshot_getter=account_snapshot_getter,
        )
    )
    logger.bind(
        component="runtime",
        process_role=process_role,
        instance_key=get_instance_key(),
    ).info("runtime_shadow.heartbeat.started")


async def stop_shadow_heartbeat() -> None:
    global _heartbeat_task, _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
    task = _heartbeat_task
    _heartbeat_task = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _heartbeat_stop = None
