"""Background worker for call_broadcast_jobs (disabled by default)."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.app_download_nurture import schedule_download_followups_after_reply
from services.call_broadcast.jobs import (
    claim_next_call_broadcast_job,
    count_active_calls_for_account,
    finalize_job,
    load_video_asset_for_job,
    mark_job_streaming,
    requeue_job,
)
from services.call_broadcast.pytgcalls_manager import pytgcalls_import_error
from services.call_broadcast.session import run_call_broadcast
from services.mtproto.account_pool import AccountPool
from services.telegram_account_manager import telegram_account_manager

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]

_ADVISORY_LOCK_KEY = 6_301_777
JOB_ID = "call_broadcast_worker_tick"
_scheduler: Optional[AsyncIOScheduler] = None
_account_pool: Optional[AccountPool] = None


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def _init_account_pool() -> None:
    global _account_pool
    if _account_pool is not None:
        return
    accounts = await telegram_account_manager.get_active_accounts()
    account_ids = [str(account.id) for account in accounts if account.is_active]
    if not account_ids:
        logger.warning("call_broadcast_worker.account_pool.empty")
        return

    async def _resolver(account_id: str):
        return await telegram_account_manager.get_client(UUID(account_id))

    _account_pool = AccountPool(account_ids=account_ids, client_resolver=_resolver)


async def _resolve_account_id(
    session: AsyncSession,
    *,
    user_id: str,
    preferred_account_id: str | None,
) -> str | None:
    if preferred_account_id:
        return preferred_account_id
    if _account_pool is None:
        return None
    route = await _account_pool.resolve_account(user_id)
    return route.account_id


async def _schedule_post_call_nurture(
    session: AsyncSession,
    *,
    job: dict[str, Any],
    trace_id: str | None,
) -> None:
    if not getattr(settings, "CALL_BROADCAST_POST_CALL_NURTURE_ENABLED", True):
        return
    if not getattr(settings, "APP_DOWNLOAD_NURTURE_ENABLED", True):
        return
    conversation_id = job.get("conversation_id")
    if not conversation_id:
        return
    await schedule_download_followups_after_reply(
        session,
        user_id=str(job["user_id"]),
        external_user_id=job.get("external_user_id"),
        conversation_id=str(conversation_id),
        chat_id=int(job["chat_id"]),
        assistant_message_id=None,
        trace_id=trace_id,
        account_id=str(job["account_id"]) if job.get("account_id") else None,
    )


async def _process_claimed_job(session: AsyncSession, job: dict[str, Any]) -> dict[str, int]:
    stats = {"completed": 0, "failed": 0, "retrying": 0}
    job_id = str(job["id"])
    trace_id = job.get("trace_id")
    log = logger.bind(component="call_broadcast_worker", trace_id=trace_id, job_id=job_id)

    account_id = await _resolve_account_id(
        session,
        user_id=str(job["user_id"]),
        preferred_account_id=str(job["account_id"]) if job.get("account_id") else None,
    )
    if not account_id:
        await finalize_job(session, job_id=job_id, status="failed", failure_reason="no_account")
        stats["failed"] = 1
        log.warning("call_broadcast_worker.no_account")
        return stats

    if job.get("account_id") is None:
        await session.execute(
            text(
                """
                UPDATE call_broadcast_jobs
                SET account_id = CAST(:account_id AS uuid), updated_at = NOW()
                WHERE id = CAST(:job_id AS uuid)
                """
            ),
            {"account_id": account_id, "job_id": job_id},
        )

    max_concurrent = int(getattr(settings, "CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT", 1))
    active = await count_active_calls_for_account(session, UUID(account_id))
    if active > max_concurrent:
        await requeue_job(session, job_id=job_id, failure_reason="account_busy")
        stats["retrying"] = 1
        return stats

    asset = await load_video_asset_for_job(
        session,
        video_asset_id=str(job["video_asset_id"]) if job.get("video_asset_id") else None,
    )
    if not asset or not str(asset.get("file_path") or "").strip():
        await finalize_job(session, job_id=job_id, status="failed", failure_reason="no_video_asset")
        stats["failed"] = 1
        log.warning("call_broadcast_worker.no_video_asset")
        return stats

    duration_seconds = int(
        asset.get("duration_seconds")
        or getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)
    )
    job_metadata = _parse_metadata(job.get("metadata"))
    raw_access_hash = job_metadata.get("telegram_access_hash")
    telegram_access_hash = (
        int(str(raw_access_hash)) if raw_access_hash is not None else None
    )

    await mark_job_streaming(session, job_id)
    await session.commit()

    try:
        await run_call_broadcast(
            account_id=UUID(account_id),
            chat_id=int(job["chat_id"]),
            video_path=str(asset["file_path"]),
            duration_seconds=duration_seconds,
            trace_id=trace_id,
            telegram_access_hash=telegram_access_hash,
        )
    except Exception as exc:
        retry_count = int(job.get("retry_count") or 0)
        max_retries = int(job.get("max_retries") or 2)
        should_retry = retry_count + 1 < max_retries
        async with AsyncSessionLocal() as retry_session:
            await finalize_job(
                retry_session,
                job_id=job_id,
                status="pending" if should_retry else "failed",
                failure_reason=str(exc)[:500],
                increment_retry=should_retry,
            )
            await retry_session.commit()
        stats["retrying" if should_retry else "failed"] = 1
        log.bind(error_type=type(exc).__name__).warning("call_broadcast_worker.stream_failed")
        return stats

    job["account_id"] = account_id
    async with AsyncSessionLocal() as done_session:
        await finalize_job(done_session, job_id=job_id, status="completed")
        try:
            await _schedule_post_call_nurture(done_session, job=job, trace_id=trace_id)
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "call_broadcast_worker.post_call_nurture_failed"
            )
        await done_session.commit()
    stats["completed"] = 1
    log.info("call_broadcast_worker.completed")
    return stats


async def run_one_tick(trace_id: str | None = None) -> dict[str, Any]:
    if not getattr(settings, "CALL_BROADCAST_ENABLED", False):
        return {"enabled": False}

    if pytgcalls_import_error():
        logger.warning(f"call_broadcast_worker.pytgcalls_unavailable: {pytgcalls_import_error()}")
        return {"enabled": True, "skipped": "pytgcalls_unavailable"}

    stats: dict[str, Any] = {
        "enabled": True,
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "retrying": 0,
    }
    log = logger.bind(component="call_broadcast_worker", trace_id=trace_id or "call-broadcast")

    if _account_pool is None:
        await _init_account_pool()
    if _account_pool is None:
        stats["skipped_no_pool"] = 1
        return stats

    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": _ADVISORY_LOCK_KEY},
            )
            job = await claim_next_call_broadcast_job(session)
            if not job:
                log.info("call_broadcast_worker.tick.empty")
                return stats
            stats["claimed"] = 1
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.bind(error_type=type(exc).__name__).error("call_broadcast_worker.claim_failed")
            stats["error"] = type(exc).__name__
            return stats

    async with AsyncSessionLocal() as session:
        try:
            tick_stats = await _process_claimed_job(session, job)
            stats.update(tick_stats)
        except Exception as exc:
            await session.rollback()
            log.bind(error_type=type(exc).__name__).error("call_broadcast_worker.process_failed")
            stats["error"] = type(exc).__name__
    return stats


def spawn_immediate_tick(*, trace_id: str | None = None) -> None:
    """Process the next pending job right away instead of waiting for the poll interval."""
    import asyncio

    asyncio.create_task(run_one_tick(trace_id=trace_id))
    logger.bind(component="call_broadcast_worker", trace_id=trace_id).info(
        "call_broadcast_worker.immediate_tick.spawned"
    )


def start_scheduler() -> None:
    global _scheduler
    if not getattr(settings, "CALL_BROADCAST_ENABLED", False):
        logger.info("Call broadcast worker disabled")
        return
    if AsyncIOScheduler is None or IntervalTrigger is None:
        logger.warning("APScheduler not available, call broadcast worker not started")
        return
    if _scheduler is not None and _scheduler.running:
        return

    import asyncio

    asyncio.create_task(_init_account_pool())
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_one_tick,
        trigger=IntervalTrigger(
            seconds=int(getattr(settings, "CALL_BROADCAST_POLL_SECONDS", 15))
        ),
        id=JOB_ID,
        max_instances=int(getattr(settings, "CALL_BROADCAST_SCHEDULER_MAX_INSTANCES", 1)),
    )
    _scheduler.start()
    logger.info("Call broadcast worker scheduler started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Call broadcast worker scheduler stopped")
