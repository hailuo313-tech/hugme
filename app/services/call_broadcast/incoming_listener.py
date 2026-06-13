"""Auto-answer inbound Telegram video calls and play the default promo video."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from loguru import logger

from core.config import settings
from core.database import AsyncSessionLocal
from services.call_broadcast.incoming_review import (
    expire_stale_operator_reviews,
    inbound_call_requires_operator_review,
    queue_inbound_operator_review,
)
from services.call_broadcast.jobs import (
    count_active_calls_for_account,
    count_completed_inbound_calls_for_chat,
    create_inbound_auto_answer_job,
    finalize_job,
    mark_job_streaming,
    resolve_inbound_sequence_video_asset,
)
from services.call_broadcast.pytgcalls_manager import get_pytgcalls, pytgcalls_import_error
from services.call_broadcast.session import run_call_broadcast
from services.telegram_account_manager import telegram_account_manager

_registered_accounts: set[str] = set()
_inflight_calls: set[tuple[str, int]] = set()
_local_active_by_account: dict[str, int] = {}
_bootstrap_task: asyncio.Task[Any] | None = None
_running = False


def _incoming_enabled() -> bool:
    return bool(
        getattr(settings, "CALL_BROADCAST_ENABLED", False)
        and getattr(settings, "CALL_BROADCAST_INCOMING_AUTO_ANSWER", False)
    )


def _extract_incoming_peer(update: Any) -> tuple[int, int | None]:
    chat_id = getattr(update, "chat_id", None)
    if chat_id is None:
        chat = getattr(update, "chat", None)
        if chat is not None:
            chat_id = getattr(chat, "id", None) or getattr(chat, "chat_id", None)
    if not chat_id:
        return 0, None

    access_hash = getattr(update, "access_hash", None)
    if access_hash is None:
        chat = getattr(update, "chat", None)
        if chat is not None:
            access_hash = getattr(chat, "access_hash", None)
    return int(chat_id), int(access_hash) if access_hash is not None else None


def _bind_incoming_handler(pytgcalls: Any, account_id: str) -> bool:
    try:
        from pytgcalls import filters as pyc_filters
        from pytgcalls.types import ChatUpdate
    except Exception as exc:
        logger.bind(account_id=account_id, error_type=type(exc).__name__).warning(
            "call_broadcast.incoming.import_failed"
        )
        return False

    handler_filter = pyc_filters.chat_update(ChatUpdate.Status.INCOMING_CALL)

    @pytgcalls.on_update(handler_filter)
    async def _on_incoming(_pytg: Any, update: ChatUpdate) -> None:
        asyncio.create_task(_handle_incoming_call(account_id, update))

    return True


async def _handle_incoming_call(account_id: str, update: Any) -> None:
    if not _incoming_enabled():
        return

    chat_id, access_hash = _extract_incoming_peer(update)
    if not chat_id:
        return

    inflight_key = (account_id, chat_id)
    if inflight_key in _inflight_calls:
        return
    _inflight_calls.add(inflight_key)

    trace_id = f"incoming-{account_id[:8]}-{chat_id}-{int(time.time())}"
    log = logger.bind(
        component="call_broadcast_incoming",
        trace_id=trace_id,
        account_id=account_id,
        chat_id=chat_id,
    )
    log.info("call_broadcast.incoming.received")

    job_id: str | None = None
    try:
        async with AsyncSessionLocal() as db:
            db_count = await count_active_calls_for_account(db, UUID(account_id))
            local_count = _local_active_by_account.get(account_id, 0)
            max_concurrent = int(
                getattr(settings, "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT", 1)
            )
            if (db_count + local_count) >= max_concurrent:
                log.bind(db_active=db_count, local_active=local_count).info(
                    "call_broadcast.incoming.busy_skip"
                )
                return

            completed_inbound = await count_completed_inbound_calls_for_chat(db, chat_id)
            if inbound_call_requires_operator_review(completed_inbound):
                job_id = await queue_inbound_operator_review(
                    db,
                    account_id=account_id,
                    chat_id=chat_id,
                    access_hash=access_hash,
                    trace_id=trace_id,
                )
                await db.commit()
                if job_id:
                    log.bind(
                        inbound_call_number=completed_inbound + 1,
                        job_id=job_id,
                    ).info("call_broadcast.incoming.operator_review_required")
                else:
                    log.warning("call_broadcast.incoming.operator_review_enqueue_failed")
                return

            asset = await resolve_inbound_sequence_video_asset(db, chat_id)
            if not asset or not asset.get("file_path"):
                log.warning("call_broadcast.incoming.no_video_asset")
                return

            inbound_call_number = int(asset.get("inbound_call_number") or 1)
            resolved_sequence = asset.get("resolved_play_sequence")
            log.bind(
                inbound_call_number=inbound_call_number,
                play_sequence=resolved_sequence,
            ).info("call_broadcast.incoming.sequence_resolved")

            video_asset_id = str(asset["id"]) if asset.get("id") else None
            job_id = await create_inbound_auto_answer_job(
                db,
                chat_id=chat_id,
                account_id=account_id,
                video_asset_id=video_asset_id,
                trace_id=trace_id,
                telegram_access_hash=access_hash,
                extra_metadata={
                    "inbound_call_number": inbound_call_number,
                    "play_sequence": resolved_sequence,
                },
            )
            await db.commit()

        _local_active_by_account[account_id] = _local_active_by_account.get(account_id, 0) + 1

        if not job_id:
            log.warning("call_broadcast.incoming.audit_job_failed")
            return

        duration = int(
            asset.get("duration_seconds")
            or getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)
        )
        async with AsyncSessionLocal() as db:
            await mark_job_streaming(db, job_id)
            await db.commit()

        await run_call_broadcast(
            account_id=UUID(account_id),
            chat_id=chat_id,
            video_path=str(asset["file_path"]),
            duration_seconds=duration,
            trace_id=trace_id,
            telegram_access_hash=access_hash,
        )

        async with AsyncSessionLocal() as db:
            await finalize_job(db, job_id=job_id, status="completed")
            await db.commit()
        log.info("call_broadcast.incoming.answered")
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("call_broadcast.incoming.failed")
        if job_id:
            try:
                async with AsyncSessionLocal() as db:
                    await finalize_job(
                        db,
                        job_id=job_id,
                        status="failed",
                        failure_reason=str(exc)[:500],
                    )
                    await db.commit()
            except Exception:
                pass
    finally:
        _inflight_calls.discard(inflight_key)
        current = _local_active_by_account.get(account_id, 0)
        if current <= 1:
            _local_active_by_account.pop(account_id, None)
        else:
            _local_active_by_account[account_id] = current - 1


async def _register_account_listener(account_id: UUID) -> bool:
    key = str(account_id)
    if key in _registered_accounts:
        return True

    wrapper = await get_pytgcalls(account_id)
    if wrapper is None:
        logger.bind(account_id=key).warning("call_broadcast.incoming.no_client")
        return False

    if not _bind_incoming_handler(wrapper, key):
        return False

    _registered_accounts.add(key)
    logger.bind(account_id=key).info("call_broadcast.incoming.listener_registered")
    return True


async def _register_all_active_accounts() -> int:
    accounts = await telegram_account_manager.get_active_accounts()
    registered = 0
    for account in accounts:
        if not getattr(account, "is_active", True):
            continue
        if await _register_account_listener(account.id):
            registered += 1
    return registered


async def _bootstrap_loop() -> None:
    while _running:
        try:
            if _incoming_enabled():
                await expire_stale_operator_reviews()
                count = await _register_all_active_accounts()
                if count:
                    logger.bind(registered=count).debug("call_broadcast.incoming.bootstrap_tick")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.incoming.bootstrap_failed"
            )
        await asyncio.sleep(60)


async def start_incoming_call_listeners() -> None:
    """Eagerly start PyTgCalls listeners for inbound auto-answer (when enabled)."""
    global _bootstrap_task, _running

    if not _incoming_enabled():
        return

    err = pytgcalls_import_error()
    if err:
        logger.warning(f"call_broadcast.incoming.pytgcalls_unavailable: {err}")
        return

    _running = True
    registered = await _register_all_active_accounts()
    logger.bind(registered=registered).info("call_broadcast.incoming.listeners_started")

    if _bootstrap_task is None or _bootstrap_task.done():
        _bootstrap_task = asyncio.create_task(_bootstrap_loop())


async def shutdown_incoming_call_listeners() -> None:
    """Stop the bootstrap loop; process exit tears down PyTgCalls handlers."""
    global _bootstrap_task, _running

    _running = False
    if _bootstrap_task is not None and not _bootstrap_task.done():
        _bootstrap_task.cancel()
        try:
            await _bootstrap_task
        except asyncio.CancelledError:
            pass
    _bootstrap_task = None
    _registered_accounts.clear()
    _inflight_calls.clear()
    _local_active_by_account.clear()
