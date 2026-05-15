"""D4-4: Profile score worker — initiation_score + trigger_threshold.

周期性扫描 ``user_profiles``：根据近 ``SCORE_INITIATION_LOOKBACK_DAYS`` 天内
``sender_type='user'`` 的消息条数计算 ``initiation_score``（0–100，按 cap 饱和），
并按配置更新 ``trigger_threshold``（与 ``LONELINESS_BASELINE`` pivot 对齐的线性式）。

调度入口：``profile_score_scheduler``；互斥 ``pg_try_advisory_lock(6_300_413)``。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger
from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal

_ADVISORY_LOCK_KEY = 6_300_413


async def run_profile_score_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    trace_id = trace_id or f"profile_score-{int(time.time())}"
    log = logger.bind(component="profile_score_worker", trace_id=trace_id)
    stats: dict[str, Any] = {
        "profiles_scanned": 0,
        "profiles_updated": 0,
        "skipped": True,
        "error": None,
    }

    lookback = max(1, int(settings.SCORE_INITIATION_LOOKBACK_DAYS or 7))
    cap = max(1, int(settings.SCORE_INITIATION_CAP_MESSAGES or 40))
    eps = float(settings.SCORE_PROFILE_MIN_UPDATE_DELTA or 0.05)

    base = float(settings.TRIGGER_THRESHOLD_BASE or 65.0)
    pivot = float(settings.TRIGGER_THRESHOLD_PIVOT or 35.0)
    k_slope = float(settings.TRIGGER_THRESHOLD_K or 0.15)
    thr_floor = float(settings.TRIGGER_THRESHOLD_FLOOR or 50.0)
    thr_ceil = float(settings.TRIGGER_THRESHOLD_CEIL or 82.0)

    try:
        async with AsyncSessionLocal() as session:
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got_lock:
                log.info("profile_score_worker.skip_no_lock")
                return stats

            try:
                profiles = (
                    await session.execute(
                        text(
                            "SELECT user_id::text, initiation_score, trigger_threshold, "
                            "loneliness_score FROM user_profiles"
                        )
                    )
                ).fetchall()

                stats["profiles_scanned"] = len(profiles or ())
                stats["skipped"] = False

                for row in profiles or ():
                    uid = str(row[0])
                    old_init = float(row[1] or 0.0)
                    old_thr = float(row[2] or 65.0)
                    loneliness = float(row[3] or settings.LONELINESS_BASELINE)

                    cnt_row = (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*)::int
                                FROM messages m
                                JOIN conversations c ON c.id = m.conversation_id
                                WHERE c.user_id = CAST(:uid AS uuid)
                                  AND m.sender_type = 'user'
                                  AND m.created_at >= NOW() - make_interval(days => :days)
                                """
                            ),
                            {"uid": uid, "days": lookback},
                        )
                    ).fetchone()
                    cnt = int(cnt_row[0] or 0) if cnt_row else 0

                    initiation = min(100.0, (cnt / float(cap)) * 100.0)

                    raw_thr = base - k_slope * (loneliness - pivot)
                    new_thr = max(thr_floor, min(thr_ceil, raw_thr))

                    if abs(initiation - old_init) < eps and abs(new_thr - old_thr) < eps:
                        continue

                    await session.execute(
                        text(
                            """
                            UPDATE user_profiles
                            SET initiation_score = :is,
                                trigger_threshold = :tt,
                                score_updated_at = NOW(),
                                updated_at = NOW()
                            WHERE user_id = CAST(:uid AS uuid)
                            """
                        ),
                        {"is": initiation, "tt": new_thr, "uid": uid},
                    )
                    stats["profiles_updated"] += 1

                await session.commit()

                log.bind(**stats).info("profile_score_worker.tick.done")

            finally:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                await session.commit()

    except Exception as exc:
        stats["error"] = f"{type(exc).__name__}:{exc}"
        log.bind(error_type=type(exc).__name__).exception(
            "profile_score_worker.tick.failed"
        )

    return stats
