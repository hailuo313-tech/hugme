"""D4-4 剩余：画像分 Worker — ``initiation_score`` + min-only ``trigger_threshold``。

**initiation_score（0–100）**
    最近 ``SCORE_INITIATION_LOOKBACK_DAYS`` 天内、``sender_type='user'`` 的消息条数，
    相对 ``SCORE_INITIATION_CAP_MESSAGES`` 线性饱和；与 ``scripts/init.sql`` 中
    ``user_profiles.initiation_score`` 默认值 0 对齐，Worker 周期性写回。

**trigger_threshold（0–100，init.sql 默认 65）**
    **min-only**：取参与维度的最小值 ``m``（loneliness 必参与；initiation>0 时参与；
    emotion / retention / dependency 仅当 >0 时参与，避免 schema 默认 0 拉低 ``m``）。
    公式（与 ``LONELINESS_BASELINE`` 冷启动对齐）::

        threshold = clamp(floor, ceil, TRIGGER_THRESHOLD_BASE
            - TRIGGER_THRESHOLD_K * (m - TRIGGER_THRESHOLD_PIVOT))

    ``m`` 越高（多维度压力越大）→ ``threshold`` 略降，便于后续与「超过阈值再 handoff」
    类产品规则衔接；冷启动 ``m≈35`` 时 ``threshold≈TRIGGER_THRESHOLD_BASE``（默认 65）。

Admin 前端 ``admin/app/users/[id]/page.tsx`` 通过 ``GET /api/v1/users/{id}/data-export``
读取 ``user_profiles`` 全行；本模块不在此改 OpenAPI schema，仅保证写回列与 DB 一致。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal

_ADVISORY_LOCK_KEY = 6_300_413
JOB_ID = "profile_score_tick"


def clamp_float(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_initiation_score_from_count(count: int, *, cap_messages: int) -> float:
    """将窗口内用户消息条数映射到 0–100。"""
    cap = max(1, int(cap_messages))
    c = max(0, int(count))
    return round(min(100.0, 100.0 * c / float(cap)), 2)


def min_score_for_trigger_threshold(
    initiation: float,
    emotion: float,
    retention: float,
    dependency: float,
    loneliness: float,
) -> float:
    """min-only 聚合：loneliness 始终参与；initiation>0 参与；
    emotion/retention/dependency 仅当 >0 时参与（未建模维度保持 schema 默认 0 不拉低 m）。
    """
    parts: list[float] = [float(loneliness)]
    if float(initiation) > 0.0:
        parts.append(float(initiation))
    for x in (emotion, retention, dependency):
        if x is not None and float(x) > 0.0:
            parts.append(float(x))
    return min(parts)


def compute_trigger_threshold_min_only(
    initiation: float,
    emotion: float,
    retention: float,
    dependency: float,
    loneliness: float,
    *,
    base: float,
    pivot: float,
    k: float,
    floor: float,
    ceil: float,
) -> float:
    m = min_score_for_trigger_threshold(
        initiation, emotion, retention, dependency, loneliness
    )
    raw = float(base) - float(k) * (m - float(pivot))
    return round(clamp_float(raw, float(floor), float(ceil)), 2)


async def _fetch_user_message_counts(
    session: AsyncSession, *, lookback_days: int
) -> dict[str, int]:
    days = max(1, min(int(lookback_days), 365))
    res = await session.execute(
        text(
            """
            SELECT c.user_id::text AS uid, COUNT(*)::bigint AS c
            FROM messages m
            INNER JOIN conversations c ON c.id = m.conversation_id
            WHERE m.sender_type = 'user'
              AND m.created_at >= NOW() - make_interval(days => :days)
            GROUP BY c.user_id
            """
        ),
        {"days": days},
    )
    out: dict[str, int] = {}
    for row in res.fetchall() or []:
        m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        uid = str(m.get("uid") or "")
        if uid:
            out[uid] = int(m.get("c") or 0)
    return out


async def run_profile_score_tick(trace_id: Optional[str] = None) -> dict[str, Any]:
    """单轮：刷新所有 ``user_profiles`` 的 initiation_score + trigger_threshold。

    Returns:
        统计 dict：``profiles_scanned``, ``profiles_updated``, ``error`` 等。
    """
    trace_id = trace_id or f"score-{int(time.time())}"
    log = logger.bind(component="profile_score_worker", trace_id=trace_id, job_id=JOB_ID)
    stats: dict[str, Any] = {
        "profiles_scanned": 0,
        "profiles_updated": 0,
        "error": None,
    }

    lookback = max(1, min(int(settings.SCORE_INITIATION_LOOKBACK_DAYS or 7), 90))
    cap_msgs = max(1, min(int(settings.SCORE_INITIATION_CAP_MESSAGES or 40), 500))

    base = float(settings.TRIGGER_THRESHOLD_BASE or 65.0)
    pivot = float(settings.TRIGGER_THRESHOLD_PIVOT or 35.0)
    k = float(settings.TRIGGER_THRESHOLD_K or 0.15)
    floor = float(settings.TRIGGER_THRESHOLD_FLOOR or 50.0)
    ceil_v = float(settings.TRIGGER_THRESHOLD_CEIL or 82.0)
    eps = float(settings.SCORE_PROFILE_MIN_UPDATE_DELTA or 0.05)

    try:
        async with AsyncSessionLocal() as session:
            got = (
                await session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
            if not got:
                log.info("profile_score_worker.skip_no_lock")
                return stats

            try:
                counts = await _fetch_user_message_counts(session, lookback_days=lookback)
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT user_id::text,
                                   initiation_score,
                                   emotion_score,
                                   retention_score,
                                   dependency_score,
                                   loneliness_score,
                                   trigger_threshold
                            FROM user_profiles
                            """
                        )
                    )
                ).fetchall()

                stats["profiles_scanned"] = len(rows or [])
                for row in rows or []:
                    m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                    uid = str(m["user_id"])
                    i0 = float(m.get("initiation_score") or 0.0)
                    e = float(m.get("emotion_score") or 0.0)
                    r = float(m.get("retention_score") or 0.0)
                    d = float(m.get("dependency_score") or 0.0)
                    l = float(m.get("loneliness_score") if m.get("loneliness_score") is not None else 35.0)
                    old_tt = float(m.get("trigger_threshold") or base)

                    new_i = compute_initiation_score_from_count(
                        counts.get(uid, 0), cap_messages=cap_msgs
                    )
                    new_tt = compute_trigger_threshold_min_only(
                        new_i,
                        e,
                        r,
                        d,
                        l,
                        base=base,
                        pivot=pivot,
                        k=k,
                        floor=floor,
                        ceil=ceil_v,
                    )

                    if (
                        abs(new_i - i0) < eps
                        and abs(new_tt - old_tt) < eps
                    ):
                        continue

                    await session.execute(
                        text(
                            """
                            UPDATE user_profiles
                            SET initiation_score = :ini,
                                trigger_threshold = :tt,
                                score_updated_at = NOW(),
                                updated_at = NOW()
                            WHERE user_id = CAST(:uid AS uuid)
                            """
                        ),
                        {"ini": new_i, "tt": new_tt, "uid": uid},
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
    except Exception as exc:  # pragma: no cover - 防御性
        stats["error"] = str(exc)
        log.bind(error_type=type(exc).__name__).exception("profile_score_worker.tick.failed")

    return stats
