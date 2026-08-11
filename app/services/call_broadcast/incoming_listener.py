"""Auto-answer inbound Telegram video calls and play the default promo video."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.call_broadcast.incoming_review import (
    expire_stale_operator_reviews,
    inbound_call_requires_operator_review,
    queue_inbound_operator_review,
)
from services.call_broadcast.jobs import (
    count_active_calls_for_account,
    count_completed_inbound_auto_answer_calls_for_chat,
    count_completed_inbound_calls_for_chat,
    count_prior_inbound_call_attempts,
    count_inbound_call_events_for_chat,
    record_inbound_call_event,
    create_inbound_auto_answer_job,
    finalize_job,
    mark_job_streaming,
    resolve_inbound_sequence_video_asset,
)
from services.call_broadcast.pytgcalls_manager import (
    get_pytgcalls,
    pytgcalls_import_error,
    reset_pytgcalls,
)
from services.call_broadcast.post_auto_answer_profile_prompt import (
    maybe_send_second_auto_answer_profile_prompt,
)
from services.call_broadcast.session import (
    peek_playback_prepare,
    prepare_call_broadcast_playback,
    resolve_call_broadcast_wall_timeout_seconds,
    run_call_broadcast,
    warm_call_broadcast_playback_cache,
)
from services.telegram_account_manager import telegram_account_manager

_registered_accounts: set[str] = set()
_inflight_calls: set[tuple[str, int]] = set()
_local_active_by_account: dict[str, int] = {}
_bootstrap_task: asyncio.Task[Any] | None = None
_running = False


async def _load_active_video_paths(db: Any) -> list[str]:
    rows = (
        await db.execute(
            text(
                """
                SELECT file_path
                FROM video_broadcast_assets
                WHERE status = 'active'
                  AND file_path IS NOT NULL
                  AND file_path <> ''
                ORDER BY play_sequence ASC NULLS LAST, created_at ASC
                """
            )
        )
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


async def _warm_inbound_playback_cache() -> None:
    if not _incoming_enabled():
        return
    try:
        async with AsyncSessionLocal() as db:
            paths = await _load_active_video_paths(db)
        if not paths:
            return
        result = await warm_call_broadcast_playback_cache(
            paths,
            trace_id="incoming-playback-warm",
        )
        logger.bind(**result, video_count=len(paths)).info(
            "call_broadcast.incoming.playback_cache_warmed"
        )
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).warning(
            "call_broadcast.incoming.playback_cache_warm_failed"
        )


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


def _incoming_call_event_key(update: Any) -> str:
    """Prefer Telegram/PyTgCalls call identity so callback retries stay idempotent."""
    candidates = [
        getattr(update, "call_id", None),
        getattr(update, "id", None),
    ]
    call = getattr(update, "call", None)
    if call is not None:
        candidates.extend((getattr(call, "id", None), getattr(call, "call_id", None)))
    for value in candidates:
        if value not in (None, ""):
            return f"telegram:{value}"
    # The in-memory inflight gate removes concurrent duplicate callbacks. This
    # fallback uniquely identifies a later, genuinely new callback in-process.
    return f"runtime:{id(update)}:{time.time_ns()}"


async def _get_account_reply_mode(db: Any, account_id: str) -> str:
    row = (
        await db.execute(
            text(
                """
                SELECT COALESCE(metadata->>'reply_mode', 'ai') AS reply_mode
                FROM telegram_accounts
                WHERE id = CAST(:account_id AS uuid)
                LIMIT 1
                """
            ),
            {"account_id": account_id},
        )
    ).first()
    if row is None:
        return "ai"
    data = row._mapping if hasattr(row, "_mapping") else row
    return "fixed" if str(data["reply_mode"]) == "fixed" else "ai"


def _auto_answer_threshold_for_reply_mode(reply_mode: str) -> int:
    if reply_mode == "fixed":
        return 2
    return int(getattr(settings, "CALL_BROADCAST_INBOUND_MANUAL_AFTER", 2))


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
        asyncio.create_task(_handle_incoming_call(account_id, update, _pytg))

    return True


async def _handle_incoming_call(
    account_id: str,
    update: Any,
    incoming_pytgcalls: Any | None = None,
) -> None:
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
    pytgcalls_warm_task: asyncio.Task[Any] | None = asyncio.create_task(
        get_pytgcalls(UUID(account_id))
    )
    try:
        async with AsyncSessionLocal() as db:
            from services.telegram_user_migration import migration_video_cutover
            from services.post_inbound_video_expert_gate import (
                ensure_release_review_after_inbound_call,
                post_inbound_video_release_review_calls,
            )

            event_key = _incoming_call_event_key(update)
            inserted = await record_inbound_call_event(
                db,
                account_id=account_id,
                chat_id=chat_id,
                event_key=event_key,
                trace_id=trace_id,
            )
            await db.commit()
            inbound_event_count = await count_inbound_call_events_for_chat(db, chat_id)
            release_review_threshold = post_inbound_video_release_review_calls()
            if inserted and inbound_event_count >= release_review_threshold:
                await ensure_release_review_after_inbound_call(
                    db, chat_id=chat_id, trace_id=trace_id
                )

            migration_cutover = await migration_video_cutover(
                db, account_id=account_id, chat_id=chat_id
            )
            db_count = await count_active_calls_for_account(db, UUID(account_id))
            local_count = _local_active_by_account.get(account_id, 0)
            if db_count == 0 and local_count > 0:
                log.bind(stale_local_active=local_count).info(
                    "call_broadcast.incoming.local_active_reset"
                )
                _local_active_by_account.pop(account_id, None)
                local_count = 0
            max_concurrent = int(
                getattr(settings, "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT", 1)
            )
            if (db_count + local_count) >= max_concurrent:
                log.bind(db_active=db_count, local_active=local_count).info(
                    "call_broadcast.incoming.busy_skip"
                )
                return

            count_scope = {
                "account_id": account_id if migration_cutover else None,
                "since": migration_cutover,
            }
            completed_playbacks = await count_completed_inbound_calls_for_chat(
                db, chat_id, **count_scope
            )
            recorded_attempts = await count_prior_inbound_call_attempts(
                db, chat_id, **count_scope
            )
            reply_mode = await _get_account_reply_mode(db, account_id)
            auto_answer_threshold = _auto_answer_threshold_for_reply_mode(reply_mode)
            if inbound_event_count >= release_review_threshold or inbound_call_requires_operator_review(
                completed_playbacks=completed_playbacks,
                recorded_attempts=recorded_attempts,
                auto_answer_threshold=auto_answer_threshold,
            ):
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
                        inbound_call_number=completed_playbacks + 1,
                        call_attempt_number=recorded_attempts + 1,
                        completed_playbacks=completed_playbacks,
                        recorded_attempts=recorded_attempts,
                        inbound_event_count=inbound_event_count,
                        release_review_threshold=release_review_threshold,
                        reply_mode=reply_mode,
                        auto_answer_threshold=auto_answer_threshold,
                        job_id=job_id,
                    ).info("call_broadcast.incoming.operator_review_required")
                else:
                    log.warning("call_broadcast.incoming.operator_review_enqueue_failed")
                return

            asset = await resolve_inbound_sequence_video_asset(
                db, chat_id, completed_count=completed_playbacks
            )
            if not asset or not asset.get("file_path"):
                log.warning("call_broadcast.incoming.no_video_asset")
                return

            inbound_call_number = int(asset.get("inbound_call_number") or 1)
            resolved_sequence = asset.get("resolved_play_sequence")
            log.bind(
                inbound_call_number=inbound_call_number,
                play_sequence=resolved_sequence,
                reply_mode=reply_mode,
                auto_answer_threshold=auto_answer_threshold,
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

        prep_timeout = int(getattr(settings, "CALL_BROADCAST_PREP_TIMEOUT_SECONDS", 180))
        prepared = peek_playback_prepare(
            video_path=str(asset["file_path"]),
            duration_seconds=duration,
        )
        if prepared is not None:
            log.info("call_broadcast.incoming.prep_cache_hit")
        else:
            log.info("call_broadcast.incoming.prep_cache_miss")
            try:
                prepared = await asyncio.wait_for(
                    prepare_call_broadcast_playback(
                        video_path=str(asset["file_path"]),
                        duration_seconds=duration,
                        trace_id=trace_id,
                    ),
                    timeout=prep_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"call broadcast prep exceeded {prep_timeout:.0f}s for chat_id={chat_id}"
                ) from exc

        if pytgcalls_warm_task is not None:
            try:
                await pytgcalls_warm_task
            except Exception as exc:
                log.bind(error_type=type(exc).__name__).warning(
                    "call_broadcast.incoming.pytgcalls_warm_failed"
                )
            pytgcalls_warm_task = None

        wall_timeout = resolve_call_broadcast_wall_timeout_seconds(prepared.playback_seconds)
        log.bind(
            playback_seconds=round(prepared.playback_seconds, 2),
            wall_timeout=round(wall_timeout, 2),
        ).info("call_broadcast.incoming.wall_timeout_resolved")
        try:
            playback = await asyncio.wait_for(
                run_call_broadcast(
                    account_id=UUID(account_id),
                    chat_id=chat_id,
                    video_path=str(asset["file_path"]),
                    duration_seconds=duration,
                    trace_id=trace_id,
                    telegram_access_hash=access_hash,
                    prepared=prepared,
                    pytgcalls=incoming_pytgcalls,
                ),
                timeout=wall_timeout,
            )
        except asyncio.TimeoutError as exc:
            await reset_pytgcalls(UUID(account_id))
            raise TimeoutError(
                f"call broadcast exceeded {wall_timeout:.0f}s for chat_id={chat_id}"
            ) from exc

        async with AsyncSessionLocal() as db:
            await finalize_job(
                db,
                job_id=job_id,
                status="completed",
                playback_result=playback,
            )
            try:
                completed_auto_answers = await count_completed_inbound_auto_answer_calls_for_chat(
                    db,
                    chat_id,
                    account_id=account_id if migration_cutover else None,
                    since=migration_cutover,
                )
                await maybe_send_second_auto_answer_profile_prompt(
                    db,
                    job_id=job_id,
                    account_id=account_id,
                    chat_id=chat_id,
                    telegram_access_hash=access_hash,
                    completed_auto_answer_count=completed_auto_answers,
                    trace_id=trace_id,
                    external_user_id=f"tg_{chat_id}",
                )
            except Exception as exc:
                log.bind(error_type=type(exc).__name__).warning(
                    "call_broadcast.incoming.post_auto_profile_prompt_failed"
                )
            await db.commit()
        log.info("call_broadcast.incoming.answered")
    except Exception as exc:
        log.bind(error_type=type(exc).__name__).warning("call_broadcast.incoming.failed")
        try:
            await reset_pytgcalls(UUID(account_id))
        except Exception:
            pass
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
        if pytgcalls_warm_task is not None and not pytgcalls_warm_task.done():
            pytgcalls_warm_task.cancel()
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
    await _warm_inbound_playback_cache()
    asyncio.create_task(_start_incoming_call_listeners_background())


async def _start_incoming_call_listeners_background() -> None:
    try:
        registered = await _register_all_active_accounts()
        logger.bind(registered=registered).info("call_broadcast.incoming.listeners_started")
    except Exception as exc:
        logger.bind(error_type=type(exc).__name__).error(
            "call_broadcast.incoming.listeners_start_failed"
        )
        return

    global _bootstrap_task
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
