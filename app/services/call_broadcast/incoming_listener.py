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
    finalize_stale_active_jobs,
    mark_job_streaming,
    resolve_inbound_sequence_video_asset,
)
from services.call_broadcast.pytgcalls_manager import (
    get_pytgcalls,
    pytgcalls_import_error,
    reset_pytgcalls,
    set_pytgcalls_on_create,
)
from services.call_broadcast.post_auto_answer_profile_prompt import (
    maybe_send_second_auto_answer_profile_prompt,
)
from services.call_broadcast.session import (
    capture_incoming_phone_call,
    peek_playback_prepare,
    prepare_call_broadcast_playback,
    resolve_call_broadcast_wall_timeout_seconds,
    restore_incoming_phone_call,
    run_call_broadcast,
    warm_call_broadcast_playback_cache,
)
from services.telegram_account_manager import telegram_account_manager

_registered_accounts: set[str] = set()
_bound_wrapper_ids: dict[str, int] = {}
_inflight_calls: set[tuple[str, int]] = set()
_local_active_by_account: dict[str, int] = {}
_stashed_live_calls: dict[tuple[str, int], tuple[Any, Any]] = {}
_consecutive_answer_timeouts: dict[str, int] = {}
_bootstrap_task: asyncio.Task[Any] | None = None
_running = False
_ANSWER_TIMEOUT_RESET_AFTER = 1
_REGISTER_CONCURRENCY = 6


def _is_answer_timeout_failure(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    return "call not answered" in message or "timedoutanswer" in message


def _incoming_failure_requires_listener_reset(
    exc: Exception,
    *,
    account_id: str | None = None,
) -> bool:
    """Reset for transport failures and repeated inbound accept timeouts.

    A single user hang-up should not recycle PyTgCalls. Two consecutive
    TimedOutAnswer results on the same account usually mean the wrapper
    can no longer accept incoming calls and must be rebuilt.
    """
    message = str(exc).strip().lower()
    expected_outcomes = (
        "is busy",
        "call declined",
        "call discarded",
        "already declined",
    )
    if any(marker in message for marker in expected_outcomes):
        if account_id:
            _consecutive_answer_timeouts.pop(account_id, None)
        return False
    if _is_answer_timeout_failure(exc):
        if not account_id:
            return True
        count = _consecutive_answer_timeouts.get(account_id, 0) + 1
        _consecutive_answer_timeouts[account_id] = count
        return count >= _ANSWER_TIMEOUT_RESET_AFTER
    if _is_missing_incoming_phone_call(exc):
        if account_id:
            _consecutive_answer_timeouts.pop(account_id, None)
        return False
    if account_id:
        _consecutive_answer_timeouts.pop(account_id, None)
    return True


def _is_missing_incoming_phone_call(exc: Exception) -> bool:
    """PyTgCalls accept() with an empty InputPhoneCall cache raises this TypeError."""
    message = str(exc).strip().lower()
    if "incoming phone call cache missing" in message:
        return True
    return isinstance(exc, TypeError) and "tlobject was expected" in message


async def _reset_account_listener(account_id: str) -> None:
    """Refresh a broken PyTgCalls wrapper and bind inbound events to the replacement."""
    _registered_accounts.discard(account_id)
    wrapper = await reset_pytgcalls(UUID(account_id))
    if wrapper is None:
        logger.bind(account_id=account_id).warning(
            "call_broadcast.incoming.listener_reset_no_client"
        )
        return
    _bound_wrapper_ids.pop(account_id, None)
    if not _bind_incoming_handler(wrapper, account_id):
        logger.bind(account_id=account_id).warning(
            "call_broadcast.incoming.listener_reset_bind_failed"
        )
        return
    _registered_accounts.add(account_id)
    logger.bind(account_id=account_id).info(
        "call_broadcast.incoming.listener_reset_registered"
    )


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


def stash_live_incoming_call(
    *,
    account_id: str,
    chat_id: int,
    peer: Any,
    pytgcalls: Any,
) -> None:
    """Keep InputPhoneCall + wrapper so operator accept can still answer the ring."""
    _stashed_live_calls[(str(account_id), int(chat_id))] = (peer, pytgcalls)


def take_stashed_live_incoming_call(
    account_id: str,
    chat_id: int,
) -> tuple[Any, Any]:
    return _stashed_live_calls.pop((str(account_id), int(chat_id)), (None, None))


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
    wrapper_id = id(pytgcalls)
    if _bound_wrapper_ids.get(account_id) == wrapper_id:
        return True
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
        # Capture InputPhoneCall in this turn, before a later PhoneCallDiscarded
        # update can drop PyTgCalls' P2P cache.
        incoming_phone_call = None
        chat_id, _ = _extract_incoming_peer(update)
        if chat_id and _pytg is not None:
            incoming_phone_call = await capture_incoming_phone_call(
                _pytg,
                chat_id,
                timeout_seconds=0.05,
            )
        asyncio.create_task(
            _handle_incoming_call(
                account_id,
                update,
                _pytg,
                incoming_phone_call=incoming_phone_call,
            )
        )

    _bound_wrapper_ids[account_id] = wrapper_id
    return True


async def _handle_incoming_call(
    account_id: str,
    update: Any,
    incoming_pytgcalls: Any | None = None,
    incoming_phone_call: Any | None = None,
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
    if not incoming_phone_call and incoming_pytgcalls is not None:
        incoming_phone_call = await capture_incoming_phone_call(
            incoming_pytgcalls,
            chat_id,
            timeout_seconds=2.0,
        )
    if incoming_phone_call:
        log.info("call_broadcast.incoming.phone_call_cached")
    else:
        log.warning("call_broadcast.incoming.phone_call_cache_empty")

    job_id: str | None = None
    send_03 = False
    pytgcalls_warm_task: asyncio.Task[Any] | None = None
    if incoming_pytgcalls is None:
        pytgcalls_warm_task = asyncio.create_task(get_pytgcalls(UUID(account_id)))
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
            send_03 = completed_playbacks >= 2

            asset = await resolve_inbound_sequence_video_asset(
                db, chat_id, completed_count=completed_playbacks
            )
            inbound_call_number = int(
                (asset or {}).get("inbound_call_number") or (completed_playbacks + 1)
            )
            resolved_sequence = (asset or {}).get("resolved_play_sequence")
            log.bind(
                inbound_call_number=inbound_call_number,
                play_sequence=resolved_sequence,
                reply_mode=reply_mode,
                auto_answer_threshold=auto_answer_threshold,
            ).info("call_broadcast.incoming.sequence_resolved")

            if inbound_call_requires_operator_review(
                completed_playbacks=completed_playbacks,
                recorded_attempts=recorded_attempts,
                auto_answer_threshold=auto_answer_threshold,
            ):
                review_job_id = await queue_inbound_operator_review(
                    db,
                    account_id=account_id,
                    chat_id=chat_id,
                    access_hash=access_hash,
                    trace_id=trace_id,
                )
                await db.commit()
                stash_live_incoming_call(
                    account_id=account_id,
                    chat_id=chat_id,
                    peer=incoming_phone_call,
                    pytgcalls=incoming_pytgcalls,
                )
                log.bind(job_id=review_job_id).info(
                    "call_broadcast.incoming.operator_review_queued"
                )
                if send_03:
                    asyncio.create_task(
                        _send_later_inbound_03(
                            account_id=account_id,
                            chat_id=chat_id,
                            access_hash=access_hash,
                            completed_playbacks=completed_playbacks,
                            trace_id=trace_id,
                        )
                    )
                return

            if not asset or not asset.get("file_path"):
                log.warning("call_broadcast.incoming.no_video_asset")
                return

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
        if send_03:
            asyncio.create_task(
                _send_later_inbound_03(
                    account_id=account_id,
                    chat_id=chat_id,
                    access_hash=access_hash,
                    completed_playbacks=completed_playbacks,
                    trace_id=trace_id,
                )
            )
        try:
            if (
                incoming_phone_call
                and incoming_phone_call is not True
                and incoming_pytgcalls is not None
            ):
                restore_incoming_phone_call(
                    incoming_pytgcalls,
                    chat_id,
                    incoming_phone_call,
                )
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
                    job_id=str(job_id) if job_id else None,
                    require_incoming_phone_call=True,
                ),
                timeout=wall_timeout,
            )
        except asyncio.TimeoutError as exc:
            await _reset_account_listener(account_id)
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
                try:
                    from services.call_broadcast.post_inbound_video_fixed_messages import (
                        maybe_send_after_two_auto_answers,
                    )

                    await maybe_send_after_two_auto_answers(
                        db,
                        account_id=account_id,
                        chat_id=chat_id,
                        telegram_access_hash=access_hash,
                        completed_auto_answer_count=completed_auto_answers,
                        trace_id=trace_id,
                        external_user_id=f"tg_{chat_id}",
                    )
                except Exception as exc:
                    log.bind(error_type=type(exc).__name__).warning(
                        "call_broadcast.incoming.post_video_fixed_01_02_failed"
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
        _consecutive_answer_timeouts.pop(account_id, None)
        log.info("call_broadcast.incoming.answered")
    except Exception as exc:
        log.bind(
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        ).warning("call_broadcast.incoming.failed")
        if _incoming_failure_requires_listener_reset(exc, account_id=account_id):
            try:
                await _reset_account_listener(account_id)
            except Exception:
                pass
        else:
            log.bind(error_type=type(exc).__name__).info(
                "call_broadcast.incoming.expected_call_outcome"
            )
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


async def _send_later_inbound_03(
    *,
    account_id: str,
    chat_id: int,
    access_hash: int | None,
    completed_playbacks: int,
    trace_id: str,
) -> None:
    try:
        from services.call_broadcast.post_inbound_video_fixed_messages import (
            maybe_send_03_on_later_inbound_call,
        )

        async with AsyncSessionLocal() as db:
            await maybe_send_03_on_later_inbound_call(
                db,
                account_id=account_id,
                chat_id=chat_id,
                telegram_access_hash=access_hash,
                completed_playbacks=completed_playbacks,
                trace_id=trace_id,
                external_user_id=f"tg_{chat_id}",
            )
            await db.commit()
    except Exception as exc:
        logger.bind(
            trace_id=trace_id,
            chat_id=chat_id,
            error_type=type(exc).__name__,
        ).warning("call_broadcast.incoming.post_video_fixed_03_failed")


async def _register_account_listener(account_id: UUID) -> bool:
    key = str(account_id)
    if key in _registered_accounts:
        return True

    from services.runtime_ownership import this_process_may_hold_telegram_session

    if not await this_process_may_hold_telegram_session(key):
        return False

    client = await telegram_account_manager.get_client(account_id)
    if client is None:
        return False

    try:
        wrapper = await asyncio.wait_for(get_pytgcalls(account_id), timeout=20)
    except Exception as exc:
        logger.bind(account_id=key, error_type=type(exc).__name__).warning(
            "call_broadcast.incoming.listener_start_timeout"
        )
        return False
    if wrapper is None:
        logger.bind(account_id=key).warning("call_broadcast.incoming.no_client")
        return False

    # Bind after start as well: some PyTgCalls versions drop handlers attached
    # only before start(), and a matching wrapper id would otherwise skip it.
    _bound_wrapper_ids.pop(key, None)
    if not _bind_incoming_handler(wrapper, key):
        return False

    _registered_accounts.add(key)
    logger.bind(account_id=key).info("call_broadcast.incoming.listener_registered")
    return True


async def _register_all_active_accounts() -> int:
    account_ids = list(getattr(telegram_account_manager, "clients", {}).keys())
    parsed: list[UUID] = []
    for account_id in account_ids:
        try:
            parsed.append(
                account_id if isinstance(account_id, UUID) else UUID(str(account_id))
            )
        except Exception:
            continue
    if not parsed:
        return 0

    sem = asyncio.Semaphore(_REGISTER_CONCURRENCY)

    async def _register_one(uid: UUID) -> bool:
        async with sem:
            try:
                return await _register_account_listener(uid)
            except Exception as exc:
                logger.bind(
                    account_id=str(uid),
                    error_type=type(exc).__name__,
                ).warning("call_broadcast.incoming.listener_register_failed")
                return False

    results = await asyncio.gather(
        *(_register_one(uid) for uid in parsed),
        return_exceptions=True,
    )
    return sum(1 for result in results if result is True)


async def _bootstrap_loop() -> None:
    while _running:
        try:
            if _incoming_enabled():
                await expire_stale_operator_reviews()
                try:
                    async with AsyncSessionLocal() as db:
                        stale = await finalize_stale_active_jobs(db)
                        await db.commit()
                    if stale:
                        logger.bind(stale_finalized=stale).warning(
                            "call_broadcast.incoming.stale_active_finalized"
                        )
                except Exception as exc:
                    logger.bind(error_type=type(exc).__name__).warning(
                        "call_broadcast.incoming.stale_active_finalize_failed"
                    )
                count = await _register_all_active_accounts()
                if count:
                    logger.bind(registered=count).debug("call_broadcast.incoming.bootstrap_tick")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning(
                "call_broadcast.incoming.bootstrap_failed"
            )
        await asyncio.sleep(15)


def schedule_register_incoming_listener(account_id: UUID) -> None:
    """Register PyTgCalls inbound handler as soon as a session connects."""
    if not _incoming_enabled() or not _running:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_register_account_listener(account_id))


async def start_incoming_call_listeners() -> None:
    """Eagerly start PyTgCalls listeners for inbound auto-answer (when enabled)."""
    global _bootstrap_task, _running

    if not _incoming_enabled():
        return

    err = pytgcalls_import_error()
    if err:
        logger.warning(f"call_broadcast.incoming.pytgcalls_unavailable: {err}")
        return

    set_pytgcalls_on_create(
        lambda wrapper, account_id: _bind_incoming_handler(wrapper, account_id)
    )
    _running = True
    await _warm_inbound_playback_cache()
    if _bootstrap_task is None or _bootstrap_task.done():
        _bootstrap_task = asyncio.create_task(_bootstrap_loop())
    asyncio.create_task(_start_incoming_call_listeners_background())


async def _start_incoming_call_listeners_background() -> None:
    try:
        registered = await _register_all_active_accounts()
        logger.bind(registered=registered).info("call_broadcast.incoming.listeners_started")
    except Exception as exc:
        logger.bind(
            error_type=type(exc).__name__,
            error=str(exc)[:500],
        ).exception(
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
    _bound_wrapper_ids.clear()
    _inflight_calls.clear()
    _local_active_by_account.clear()
