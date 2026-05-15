"""D4-4：``profile_score_worker`` 的 APScheduler 包装。

``SCORE_WORKER_ENABLED=False`` 时 ``start_scheduler`` no-op。
"""
from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from core.config import settings
from services.profile_score_worker import run_profile_score_tick

JOB_ID = "profile_score_interval"
_scheduler: Optional[AsyncIOScheduler] = None


async def _job() -> None:
    await run_profile_score_tick()


def start_scheduler() -> Optional[AsyncIOScheduler]:
    global _scheduler
    if not settings.SCORE_WORKER_ENABLED:
        logger.bind(component="profile_score_scheduler").info(
            "profile_score.scheduler.disabled"
        )
        return None
    if _scheduler is not None:
        return _scheduler

    poll = max(30, int(settings.SCORE_WORKER_POLL_SECONDS or 120))
    max_inst = max(1, int(settings.SCORE_WORKER_SCHEDULER_MAX_INSTANCES or 1))
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _job,
        IntervalTrigger(seconds=poll),
        id=JOB_ID,
        max_instances=max_inst,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.bind(
        component="profile_score_scheduler",
        poll_seconds=poll,
        max_instances=max_inst,
    ).info("profile_score.scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.bind(component="profile_score_scheduler").exception(
            "profile_score.scheduler.shutdown_error"
        )
    _scheduler = None
    logger.bind(component="profile_score_scheduler").info(
        "profile_score.scheduler.stopped"
    )
