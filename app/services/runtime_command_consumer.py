"""Real Telegram Runtime command consumer.

Claims owner=runtime commands and actually executes send/connect/answer/reject.
The dedicated telegram_runtime process starts this; PROCESS_ROLE=all does not.
Shadow consumers must not claim these command types.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text

from core.process_role import is_dedicated_telegram_runtime, is_shadow_runtime
from services.telegram_command_gateway import INTERACTIVE_COMMAND_TYPES
from services.runtime_ownership import (
    get_account_ownership,
    this_process_may_hold_telegram_session,
)
from services.runtime_shadow_consumer import (
    CONNECT_COMMAND_TYPES,
    FORBIDDEN_COMMAND_TYPES,
    PostgresCommandStore,
    SEND_COMMAND_TYPES,
    is_missing_runtime_schema,
)


REAL_CLAIM_SQL = """
WITH picked AS (
    SELECT id
    FROM runtime_commands
    WHERE status = 'pending'
      AND available_at <= NOW()
      AND (
          (
            CAST(:only_interactive AS integer) = 0
            AND NOT (
              command_type IN ('send_message', 'send_media')
              AND LOWER(COALESCE(payload->>'operator_confirmed', 'false')) IN ('true', '1', 't')
            )
          )
          OR (
            CAST(:only_interactive AS integer) = 1
            AND (
              command_type IN (
                  'delete_account',
                  'disconnect_account',
                  'answer_call',
                  'reject_call',
                  'hangup_call'
              )
              OR (
                  command_type IN ('send_message', 'send_media')
                  AND LOWER(COALESCE(payload->>'operator_confirmed', 'false')) IN ('true', '1', 't')
              )
            )
          )
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


class RuntimeCommandStore(PostgresCommandStore):
    """Same store as shadow, but claims send/connect/answer/reject commands."""

    async def claim(
        self,
        owner: str,
        *,
        limit: int = 10,
        lease_seconds: int = 30,
        now=None,
        only_interactive: bool = False,
    ) -> list[dict]:
        result = await self.session.execute(
            text(REAL_CLAIM_SQL),
            {
                "owner": owner,
                "limit": int(limit),
                "lease_seconds": int(lease_seconds),
                "only_interactive": 1 if only_interactive else 0,
            },
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


_consumer_task: asyncio.Task | None = None
_priority_consumer_task: asyncio.Task | None = None
_consumer_stop: asyncio.Event | None = None
_schema_missing_until = 0.0


def reset_runtime_consumer_state() -> None:
    global _consumer_task, _priority_consumer_task, _consumer_stop, _schema_missing_until
    _consumer_task = None
    _priority_consumer_task = None
    _consumer_stop = None
    _schema_missing_until = 0.0


def _payload(command: dict) -> dict:
    raw = command.get("payload") or {}
    return raw if isinstance(raw, dict) else {}


def _is_operator_confirmed(payload: dict) -> bool:
    value = payload.get("operator_confirmed")
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"true", "1", "t", "yes"}


async def execute_runtime_command(command: dict) -> dict:
    """Execute one claimed runtime command. Never sends on a shadow process."""
    if is_shadow_runtime():
        return {
            "executed": False,
            "status": "failed",
            "reason": "shadow_must_not_execute",
            "command_type": command.get("command_type"),
        }

    command_type = str(command.get("command_type") or "")
    account_id = command.get("account_id")
    payload = _payload(command)
    ownership = await get_account_ownership(str(account_id) if account_id else None)
    if not ownership.is_runtime:
        return {
            "executed": False,
            "status": "failed",
            "reason": "not_runtime_owned",
            "command_type": command_type,
        }
    if int(command.get("generation") or 0) < int(ownership.generation or 0):
        return {
            "executed": False,
            "status": "failed",
            "reason": "stale_generation",
            "command_type": command_type,
        }
    if account_id and not await this_process_may_hold_telegram_session(str(account_id)):
        if command_type != "delete_account":
            return {
                "executed": False,
                "status": "failed",
                "reason": "this_process_may_not_hold",
                "command_type": command_type,
            }

    if payload.get("runtime_probe") is True:
        if command_type not in FORBIDDEN_COMMAND_TYPES and command_type != "send_message":
            return {
                "executed": False,
                "status": "failed",
                "reason": "runtime_probe_unsupported",
                "command_type": command_type,
            }
        return {
            "executed": True,
            "status": "succeeded",
            "reason": "runtime_probe_executed",
            "command_type": command_type,
        }

    try:
        if command_type in {"send_message", "send_media", "send_text", "outbound_message"} and account_id:
            from core.database import AsyncSessionLocal
            from services.outbound_account_gate import check_outbound_account, check_recovery_send_quota
            operator_confirmed = _is_operator_confirmed(payload)
            async with AsyncSessionLocal() as gate_db:
                allowed, reason, retry_at = await check_outbound_account(
                    gate_db,
                    str(account_id),
                    allow_operator_reply=operator_confirmed,
                )
                if allowed and not operator_confirmed:
                    allowed, reason, retry_at = await check_recovery_send_quota(gate_db, str(account_id))
            if not allowed:
                return {"executed": False, "status": "failed", "reason": reason,
                        "retry_at": retry_at.isoformat() if retry_at else None}
        result = await _dispatch_real_command(command_type, account_id, payload)
    except Exception as exc:
        error_type = type(exc).__name__
        if account_id and error_type in {
            "PeerFloodError",
            "UserRestrictedError",
            "UserDeactivatedBanError",
        }:
            try:
                from core.database import AsyncSessionLocal
                from services.outbound_account_gate import pause_outbound_account

                async with AsyncSessionLocal() as db:
                    await pause_outbound_account(
                        db,
                        str(account_id),
                        reason=f"runtime_send_{error_type}",
                        hours=24,
                    )
                    await db.commit()
            except Exception:
                logger.bind(
                    component="runtime",
                    account_id=str(account_id),
                    error_type=error_type,
                ).exception("runtime_consumer.account_pause_failed")
        logger.bind(
            component="runtime",
            command_type=command_type,
            account_id=str(account_id) if account_id else None,
            error_type=error_type,
        ).warning("runtime_consumer.execute_failed")
        return {
            "executed": False,
            "status": "failed",
            "reason": error_type,
            "command_type": command_type,
        }
    result.setdefault("command_type", command_type)
    return result


async def _dispatch_real_command(
    command_type: str,
    account_id: Any,
    payload: dict,
) -> dict:
    from services.telegram_account_manager import telegram_account_manager

    account_uuid = UUID(str(account_id)) if account_id else None
    if command_type == "connect_account":
        if account_uuid is None:
            return {"executed": False, "status": "failed", "reason": "account_id_required"}
        ok = await telegram_account_manager.connect_account(account_uuid)
        return {
            "executed": bool(ok),
            "status": "succeeded" if ok else "failed",
            "reason": "connect_account",
        }
    if command_type == "disconnect_account":
        if account_uuid is None:
            return {"executed": False, "status": "failed", "reason": "account_id_required"}
        ok = await telegram_account_manager.disconnect_account(account_uuid)
        return {
            "executed": bool(ok),
            "status": "succeeded" if ok else "failed",
            "reason": "disconnect_account",
        }
    if command_type == "delete_account":
        if account_uuid is None:
            return {"executed": False, "status": "failed", "reason": "account_id_required"}
        from sqlalchemy.exc import IntegrityError

        try:
            ok = await telegram_account_manager.delete_account(account_uuid)
        except IntegrityError:
            return {
                "executed": False,
                "status": "failed",
                "reason": "account_has_dependencies",
            }
        return {
            "executed": bool(ok),
            "status": "succeeded" if ok else "failed",
            "reason": "delete_account" if ok else "account_not_found",
        }
    if command_type in {"sync_account", "reconnect_account", "sync_profiles"}:
        if command_type == "sync_profiles":
            stats = await telegram_account_manager.sync_connected_account_profiles()
            return {
                "executed": True,
                "status": "succeeded",
                "reason": "sync_profiles",
                **{key: stats[key] for key in ("total", "synced", "skipped", "failed") if key in stats},
            }
        if account_uuid is None:
            return {"executed": False, "status": "failed", "reason": "account_id_required"}
        if command_type == "reconnect_account":
            await telegram_account_manager.disconnect_account(account_uuid)
        ok = await telegram_account_manager.connect_account(account_uuid)
        return {
            "executed": bool(ok),
            "status": "succeeded" if ok else "failed",
            "reason": command_type,
        }
    if command_type in {"send_message", "send_text", "outbound_message"}:
        return await _execute_send(account_uuid, payload)
    if command_type == "send_media":
        return await _execute_send_media(account_uuid, payload)
    if command_type == "answer_call":
        return await _execute_answer_call(account_uuid, payload)
    if command_type == "reject_call":
        return await _execute_reject_call(account_uuid, payload)
    if command_type == "backfill_phone_country":
        from services.mtproto.phone_country_backfill import backfill_missing_phone_countries

        dry_run = bool(payload.get("dry_run", True))
        limit = int(payload.get("limit") or 50)
        background = bool(payload.get("background")) or (not dry_run and limit > 80)
        if background:
            from services.mtproto.phone_country_backfill import start_phone_country_backfill

            started = start_phone_country_backfill(dry_run=dry_run, limit=limit)
            return {
                "executed": True,
                "status": "succeeded",
                "reason": "backfill_phone_country_started",
                **started,
            }
        stats = await backfill_missing_phone_countries(
            dry_run=dry_run,
            limit=limit,
        )
        return {
            "executed": True,
            "status": "succeeded",
            "reason": "backfill_phone_country",
            **stats,
        }
    if command_type == "backfill_inbound_photos":
        from services.mtproto.inbound_media import backfill_missing_inbound_photos

        stats = await backfill_missing_inbound_photos()
        return {
            "executed": True,
            "status": "succeeded",
            "reason": "backfill_inbound_photos",
            **stats,
        }
    if command_type == "account_health_check":
        from services.telegram_account_health import run_health_check

        run_type = str(payload.get("run_type") or "manual")
        counts = await run_health_check(run_type)
        return {
            "executed": True,
            "status": "succeeded",
            "reason": "account_health_check",
            **counts,
        }
    if command_type in CONNECT_COMMAND_TYPES or command_type in SEND_COMMAND_TYPES:
        return {
            "executed": False,
            "status": "failed",
            "reason": f"executor_not_wired:{command_type}",
        }
    return {
        "executed": False,
        "status": "failed",
        "reason": f"unknown_command:{command_type}",
    }


async def _execute_send(account_uuid: UUID | None, payload: dict) -> dict:
    from services.mtproto.human_like_send import send_human_like_message
    from services.telegram_account_manager import telegram_account_manager

    if account_uuid is None:
        return {"executed": False, "status": "failed", "reason": "account_id_required"}
    client = await telegram_account_manager.get_client(account_uuid)
    if client is None:
        connected = await telegram_account_manager.connect_account(account_uuid)
        if connected:
            client = await telegram_account_manager.get_client(account_uuid)
    if client is None:
        return {"executed": False, "status": "failed", "reason": "client_not_connected"}
    content = str(payload.get("content") or payload.get("text") or "")
    chat_id = payload.get("chat_id")
    if not content or chat_id is None:
        return {"executed": False, "status": "failed", "reason": "send_payload_incomplete"}
    from services.mtproto.peer_resolve import resolve_telethon_peer

    peer = await resolve_telethon_peer(
        client,
        int(chat_id),
        access_hash=payload.get("access_hash"),
    )
    if payload.get("fixed_followup_message_id"):
        from services.fixed_followup_ai import send_guarded
        return await send_guarded(client, peer, content, account_uuid, payload)
    if _is_operator_confirmed(payload):
        sent = await client.send_message(peer, content)
    else:
        sent = await send_human_like_message(client, peer, content)
    sent_id = getattr(sent, "id", None)
    return {
        "executed": True,
        "status": "succeeded",
        "reason": "send_message",
        "message_id": str(sent_id) if sent_id is not None else None,
    }


async def _execute_send_media(account_uuid: UUID | None, payload: dict) -> dict:
    from services.mtproto.peer_resolve import resolve_telethon_peer
    from services.telegram_account_manager import telegram_account_manager

    if account_uuid is None:
        return {"executed": False, "status": "failed", "reason": "account_id_required"}
    client = await telegram_account_manager.get_client(account_uuid)
    if client is None:
        connected = await telegram_account_manager.connect_account(account_uuid)
        if connected:
            client = await telegram_account_manager.get_client(account_uuid)
    if client is None:
        return {"executed": False, "status": "failed", "reason": "client_not_connected"}
    chat_id = payload.get("chat_id")
    media_path = str(payload.get("media_path") or "").strip()
    media_type = str(payload.get("media_type") or "").strip().lower()
    if chat_id is None or not media_path or media_type not in {"image", "video", "audio"}:
        return {"executed": False, "status": "failed", "reason": "media_payload_incomplete"}
    path = Path(media_path)
    if not path.is_file():
        return {"executed": False, "status": "failed", "reason": "media_file_missing"}
    peer = await resolve_telethon_peer(
        client,
        int(chat_id),
        access_hash=payload.get("access_hash"),
    )
    sent = await client.send_file(
        peer,
        str(path),
        caption=str(payload.get("caption") or "").strip() or None,
        supports_streaming=media_type == "video",
        voice_note=media_type == "audio" and path.suffix.lower() in {".ogg", ".opus"},
    )
    sent_id = getattr(sent, "id", None)
    return {
        "executed": True,
        "status": "succeeded",
        "reason": "send_media",
        "message_id": str(sent_id) if sent_id is not None else None,
    }


def _payload_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_operator_confirmed(payload: dict) -> bool:
    value = payload.get("operator_confirmed")
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true", "1", "t"}


def _metadata_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def _resolve_answer_call_params(payload: dict) -> dict[str, Any]:
    """Fill video_path / chat_id / access_hash from job or asset when omitted."""
    chat_id = _payload_int(payload.get("chat_id"))
    video_path = str(payload.get("video_path") or "").strip()
    duration_seconds = _payload_int(payload.get("duration_seconds"))
    access_hash = _payload_int(payload.get("access_hash"))
    job_id = str(payload.get("job_id") or "").strip() or None
    video_asset_id = str(payload.get("video_asset_id") or "").strip() or None
    trace_id = str(payload.get("trace_id") or "")

    needs_lookup = (not video_path or chat_id is None or access_hash is None) and (
        job_id or video_asset_id
    )
    if needs_lookup:
        from core.database import AsyncSessionLocal
        from services.call_broadcast.jobs import load_call_broadcast_job, load_video_asset_for_job

        async with AsyncSessionLocal() as db:
            job = await load_call_broadcast_job(db, job_id) if job_id else None
            if job:
                if chat_id is None:
                    chat_id = _payload_int(job.get("chat_id"))
                if not video_asset_id and job.get("video_asset_id"):
                    video_asset_id = str(job["video_asset_id"])
                if not trace_id:
                    trace_id = str(job.get("trace_id") or "")
                if access_hash is None:
                    meta = _metadata_dict(job.get("metadata"))
                    access_hash = _payload_int(meta.get("telegram_access_hash"))
            if not video_path:
                asset = await load_video_asset_for_job(db, video_asset_id=video_asset_id)
                if asset:
                    video_path = str(asset.get("file_path") or "").strip()
                    if duration_seconds is None:
                        duration_seconds = _payload_int(asset.get("duration_seconds"))

    return {
        "chat_id": chat_id,
        "video_path": video_path,
        "duration_seconds": duration_seconds or 30,
        "access_hash": access_hash,
        "job_id": job_id,
        "trace_id": trace_id,
    }


async def _execute_answer_call(account_uuid: UUID | None, payload: dict) -> dict:
    if account_uuid is None:
        return {"executed": False, "status": "failed", "reason": "account_id_required"}
    params = await _resolve_answer_call_params(payload)
    video_path = str(params.get("video_path") or "")
    chat_id = params.get("chat_id")
    job_id = params.get("job_id")
    if not video_path or chat_id is None:
        return {"executed": False, "status": "failed", "reason": "answer_payload_incomplete"}

    if job_id:
        from core.database import AsyncSessionLocal
        from services.call_broadcast.jobs import mark_job_streaming

        async with AsyncSessionLocal() as db:
            await mark_job_streaming(db, job_id)
            await db.commit()

    try:
        from services.call_broadcast.incoming_listener import take_stashed_live_incoming_call
        from services.call_broadcast.session import restore_incoming_phone_call, run_call_broadcast

        peer, wrapper = take_stashed_live_incoming_call(str(account_uuid), int(chat_id))
        if wrapper is not None and peer not in (None, True, False):
            restore_incoming_phone_call(wrapper, int(chat_id), peer)
        playback = await run_call_broadcast(
            account_id=account_uuid,
            chat_id=int(chat_id),
            video_path=video_path,
            duration_seconds=int(params.get("duration_seconds") or 30),
            trace_id=str(params.get("trace_id") or ""),
            telegram_access_hash=params.get("access_hash"),
            job_id=str(job_id) if job_id else None,
            pytgcalls=wrapper,
            require_incoming_phone_call=bool(wrapper is not None and peer not in (None, True, False)),
        )
    except Exception as exc:
        if job_id:
            from core.database import AsyncSessionLocal
            from services.call_broadcast.jobs import finalize_job

            async with AsyncSessionLocal() as db:
                await finalize_job(
                    db,
                    job_id=job_id,
                    status="failed",
                    failure_reason=str(exc)[:500],
                )
                await db.commit()
        return {
            "executed": False,
            "status": "failed",
            "reason": type(exc).__name__,
        }

    if job_id:
        from core.database import AsyncSessionLocal
        from services.call_broadcast.jobs import finalize_job

        async with AsyncSessionLocal() as db:
            await finalize_job(
                db,
                job_id=job_id,
                status="completed",
                playback_result=playback,
            )
            await db.commit()
    return {
        "executed": True,
        "status": "succeeded",
        "reason": "answer_call",
        "playback": playback,
    }


async def _execute_reject_call(account_uuid: UUID | None, payload: dict) -> dict:
    from services.call_broadcast.session import reject_inbound_call

    if account_uuid is None:
        return {"executed": False, "status": "failed", "reason": "account_id_required"}
    chat_id = payload.get("chat_id")
    if chat_id is None:
        return {"executed": False, "status": "failed", "reason": "reject_payload_incomplete"}
    try:
        from services.call_broadcast.incoming_listener import take_stashed_live_incoming_call

        take_stashed_live_incoming_call(str(account_uuid), int(chat_id))
    except Exception:
        pass
    await reject_inbound_call(
        account_id=account_uuid,
        chat_id=int(chat_id),
        trace_id=str(payload.get("trace_id") or ""),
    )
    return {"executed": True, "status": "succeeded", "reason": "reject_call"}


async def process_claimed_runtime_commands(
    store: PostgresCommandStore,
    commands: list[dict],
    *,
    owner: str,
    lease_seconds: int = 30,
) -> dict:
    stats = {"claimed": len(commands), "succeeded": 0, "rejected": 0}
    queue = sorted(
        list(commands),
        key=lambda item: 0 if str(item.get("command_type") or "") in INTERACTIVE_COMMAND_TYPES else 1,
    )
    while queue:
        command = queue.pop(0)
        outcome = await execute_runtime_command(command)
        finished = await store.finish(
            str(command["id"]),
            owner=owner,
            status=str(outcome.get("status") or "failed"),
            result={
                "shadow": False,
                "executed": bool(outcome.get("executed")),
                "reason": outcome.get("reason"),
                "command_type": command.get("command_type"),
                **{
                    key: outcome[key]
                    for key in (
                        "dry_run",
                        "candidates",
                        "checked",
                        "hit",
                        "empty",
                        "client_missing",
                        "errors",
                        "written",
                        "error_types",
                        "samples",
                        "message_id",
                    )
                    if key in outcome
                },
            },
            error=None if outcome.get("executed") else str(outcome.get("reason") or "failed"),
        )
        await store.append_event(
            {
                "command_id": str(command["id"]),
                "account_id": command.get("account_id"),
                "event_type": "runtime.executed" if outcome.get("executed") else "runtime.rejected",
                "payload": outcome,
                "generation": command.get("generation"),
                "instance_key": owner,
                "trace_id": command.get("trace_id"),
            }
        )
        if not finished:
            continue
        if outcome.get("executed"):
            stats["succeeded"] += 1
        else:
            stats["rejected"] += 1
        claim = getattr(store, "claim", None)
        if not callable(claim):
            continue
        try:
            extra = await claim(
                owner,
                limit=5,
                lease_seconds=lease_seconds,
                only_interactive=True,
            )
        except TypeError:
            extra = []
        if extra:
            stats["claimed"] += len(extra)
            queue = list(extra) + queue
    return stats


async def run_runtime_consumer_once(
    store: PostgresCommandStore,
    *,
    owner: str,
    limit: int = 10,
    lease_seconds: int = 30,
    only_interactive: bool = False,
) -> dict:
    reclaimed = await store.reclaim_expired()
    claimed = await store.claim(
        owner,
        limit=limit,
        lease_seconds=lease_seconds,
        only_interactive=only_interactive,
    )
    processed = await process_claimed_runtime_commands(
        store, claimed, owner=owner, lease_seconds=lease_seconds
    )
    return {"reclaimed": len(reclaimed), **processed}


async def _postgres_tick(
    *, owner: str, limit: int, lease_seconds: int, only_interactive: bool = False
) -> dict:
    global _schema_missing_until
    now = time.time()
    if now < _schema_missing_until:
        return {"claimed": 0, "skipped": "schema_missing"}
    from core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            store = RuntimeCommandStore(session)
            return await run_runtime_consumer_once(
                store,
                owner=owner,
                limit=limit,
                lease_seconds=lease_seconds,
                only_interactive=only_interactive,
            )
    except Exception as exc:
        if is_missing_runtime_schema(exc):
            _schema_missing_until = now + 30
            logger.bind(component="runtime", error_type=type(exc).__name__).warning(
                "runtime_consumer.schema_missing"
            )
            return {"claimed": 0, "skipped": "schema_missing"}
        raise


async def _consumer_loop(
    *,
    owner: str,
    poll_seconds: float,
    limit: int,
    lease_seconds: int,
    only_interactive: bool = False,
) -> None:
    assert _consumer_stop is not None
    while not _consumer_stop.is_set():
        try:
            stats = await _postgres_tick(
                owner=owner,
                limit=limit,
                lease_seconds=lease_seconds,
                only_interactive=only_interactive,
            )
            if stats.get("claimed"):
                logger.bind(component="runtime", **stats).info("runtime_consumer.tick")
        except Exception as exc:
            logger.bind(component="runtime", error_type=type(exc).__name__).warning(
                "runtime_consumer.tick_failed"
            )
        try:
            await asyncio.wait_for(_consumer_stop.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            continue


async def start_runtime_consumer(
    *,
    owner: str | None = None,
    poll_seconds: float = 2.0,
    limit: int = 10,
    lease_seconds: int = 30,
) -> None:
    global _consumer_task, _priority_consumer_task, _consumer_stop
    if not is_dedicated_telegram_runtime():
        logger.bind(component="runtime").info("runtime_consumer.skipped")
        return
    await stop_runtime_consumer()
    from services.runtime_shadow_state import get_instance_key

    lease_owner = owner or f"runtime:{get_instance_key()}"
    _consumer_stop = asyncio.Event()
    _consumer_task = asyncio.create_task(
        _consumer_loop(
            owner=lease_owner,
            poll_seconds=max(0.2, float(poll_seconds)),
            limit=max(1, int(limit)),
            lease_seconds=max(5, int(lease_seconds)),
        )
    )
    _priority_consumer_task = asyncio.create_task(
        _consumer_loop(
            owner=f"{lease_owner}:operator",
            poll_seconds=0.2,
            limit=5,
            lease_seconds=max(5, int(lease_seconds)),
            only_interactive=True,
        )
    )
    logger.bind(component="runtime", lease_owner=lease_owner).info("runtime_consumer.started")
    from services.fixed_followup_ai import start as start_fixed_followup_ai
    await start_fixed_followup_ai()


async def stop_runtime_consumer() -> None:
    global _consumer_task, _priority_consumer_task, _consumer_stop
    if _consumer_stop is not None:
        _consumer_stop.set()
    tasks = [task for task in (_consumer_task, _priority_consumer_task) if task is not None]
    _consumer_task = None
    _priority_consumer_task = None
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    _consumer_stop = None
    if tasks:
        logger.bind(component="runtime").info("runtime_consumer.stopped")
