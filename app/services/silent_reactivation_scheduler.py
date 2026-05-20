"""
D6-3 Scheduler —— 用 APScheduler 在 FastAPI 内嵌定时调度 silent_reactivation 扫描。

设计要点
--------
- 仅当 ``settings.SILENT_REACTIVATION_ENABLED`` 为 True 时才注册 job；否则
  ``start_scheduler`` 直接 no-op，保留总开关的"零副作用"语义。
- cron 表达式从 ``settings.SILENT_REACTIVATION_CRON`` 读，默认 ``0 2 * * *`` (UTC)。
- uvicorn 默认 ``--workers 2``，每个 worker 进程都会创建自己的 scheduler。
  为避免重复扫描，job 函数先尝试拿 Postgres advisory lock；抢不到就 early-return。
  这样后续部署多实例（k8s 多 pod）也是安全的——同一 DB 同一时刻只跑一份。
- 任何异常都吞掉并 log；scheduler 不应该把 API 进程拖崩。
"""

from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from services.silent_reactivation_runner import run_silent_reactivation_scan

# 任意但固定的 64-bit 整数，作为 pg_try_advisory_lock 的 key。
# 取值固定即可，与其他业务避免冲突；这里用 D6-3 的语义化数字。
_ADVISORY_LOCK_KEY = 6_300_001

JOB_ID = "silent_reactivation_scan"

_scheduler: Optional[AsyncIOScheduler] = None


async def _run_scan_job() -> None:
    """APScheduler 触发的入口；抢 advisory lock，跑一次 scan。"""
    log = logger.bind(component="silent_reactivation", scheduler_job_id=JOB_ID)
    try:
        async with AsyncSessionLocal() as session:
            got_lock_row = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got_lock_row:
                log.info("silent_reactivation.scheduler.skip_no_lock")
                return
            try:
                log.info("silent_reactivation.scheduler.tick")
                await run_silent_reactivation_scan(session)
            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                await session.commit()
    except Exception:
        log.exception("silent_reactivation.scheduler.error")


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """启动并保存 scheduler 单例。SILENT_REACTIVATION_ENABLED=False 时 no-op。"""
    global _scheduler
    if not settings.SILENT_REACTIVATION_ENABLED:
        logger.bind(component="silent_reactivation").info("silent_reactivation.scheduler.disabled")
        return None
    if _scheduler is not None:
        return _scheduler

    try:
        trigger = CronTrigger.from_crontab(settings.SILENT_REACTIVATION_CRON, timezone="UTC")
    except Exception:
        logger.bind(
            component="silent_reactivation",
            cron=settings.SILENT_REACTIVATION_CRON,
        ).exception("silent_reactivation.scheduler.invalid_cron")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_scan_job,
        trigger=trigger,
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.bind(
        component="silent_reactivation",
        cron=settings.SILENT_REACTIVATION_CRON,
    ).info("silent_reactivation.scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    """优雅关闭 scheduler。"""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.bind(component="silent_reactivation").exception("silent_reactivation.scheduler.shutdown_error")
    finally:
        _scheduler = None
        logger.bind(component="silent_reactivation").info("silent_reactivation.scheduler.stopped")
