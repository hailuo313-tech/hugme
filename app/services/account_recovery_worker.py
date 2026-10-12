"""Safely release Telegram accounts after restriction cooldowns."""
from __future__ import annotations

import asyncio
from loguru import logger
from sqlalchemy import text
from core.database import AsyncSessionLocal

_TASK: asyncio.Task | None = None
_STOP = asyncio.Event()
_LOCK_KEY = 847362915

async def run_recovery_cycle() -> dict[str, int]:
    stats = {"stage1": 0, "stage2": 0, "stage3": 0, "completed": 0}
    async with AsyncSessionLocal() as db:
        locked = (await db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY})).scalar()
        if not locked:
            return stats
        try:
            for key, sql in (
                ("completed", """UPDATE video_reinvite_account_state SET pause_reason=NULL,paused_at=NULL,resume_at=NULL,tier_changed_at=NOW(),updated_at=NOW() WHERE status='active' AND pause_reason='recovery_limited_stage_3' AND tier_changed_at<=NOW()-INTERVAL '24 hours' RETURNING account_id"""),
                ("stage3", """UPDATE video_reinvite_account_state SET pause_reason='recovery_limited_stage_3',effective_daily_limit=60,effective_min_interval_seconds=300,tier_changed_at=NOW(),updated_at=NOW() WHERE status='active' AND pause_reason='recovery_limited_stage_2' AND tier_changed_at<=NOW()-INTERVAL '18 hours' RETURNING account_id"""),
                ("stage2", """UPDATE video_reinvite_account_state SET pause_reason='recovery_limited_stage_2',effective_daily_limit=30,effective_min_interval_seconds=600,tier_changed_at=NOW(),updated_at=NOW() WHERE status='active' AND pause_reason='recovery_limited_stage_1' AND tier_changed_at<=NOW()-INTERVAL '6 hours' RETURNING account_id"""),
            ):
                stats[key] = int((await db.execute(text(sql))).rowcount or 0)
            recent_batch = (await db.execute(text("SELECT EXISTS(SELECT 1 FROM video_reinvite_account_state WHERE pause_reason='recovery_limited_stage_1' AND tier_changed_at>NOW()-INTERVAL '6 hours')"))).scalar()
            if not recent_batch:
                stats["stage1"] = int((await db.execute(text("""
                    WITH eligible AS (
                      SELECT s.account_id FROM video_reinvite_account_state s
                      JOIN telegram_accounts a ON a.id=s.account_id
                      WHERE s.status='paused' AND s.health_check_status='healthy'
                        AND s.resume_at IS NOT NULL AND s.resume_at<=NOW()
                        AND s.pause_reason ILIKE '%PeerFlood%'
                        AND a.status='connected' AND a.is_active
                      ORDER BY COALESCE(s.last_peer_flood_at,s.last_restricted_at,s.paused_at)
                      LIMIT 5 FOR UPDATE OF s SKIP LOCKED
                    )
                    UPDATE video_reinvite_account_state s
                    SET status='active',pause_reason='recovery_limited_stage_1',
                        effective_daily_limit=12,effective_min_interval_seconds=1200,
                        tier_changed_at=NOW(),updated_at=NOW()
                    FROM eligible e WHERE e.account_id=s.account_id RETURNING s.account_id
                """))).rowcount or 0)
            await db.commit()
            logger.bind(**stats).info("account_recovery.cycle_completed")
            return stats
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})

async def _loop() -> None:
    await asyncio.sleep(120)
    while not _STOP.is_set():
        try:
            await run_recovery_cycle()
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).exception("account_recovery.cycle_failed")
        try:
            await asyncio.wait_for(_STOP.wait(), timeout=600)
        except asyncio.TimeoutError:
            pass

def start_scheduler() -> None:
    global _TASK
    if _TASK is not None and not _TASK.done():
        return
    _STOP.clear()
    _TASK = asyncio.create_task(_loop())
    logger.info("account_recovery.scheduler_started")

def shutdown_scheduler() -> None:
    _STOP.set()
    if _TASK is not None:
        _TASK.cancel()
