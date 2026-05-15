"""
D6-3 Runner —— 扫候选用户、调 ``evaluate_user``、为合格用户插 ``notification_tasks``。

设计要点
--------
- ``SILENT_REACTIVATION_ENABLED=False`` 时直接 short-circuit，不查 DB。
- 单次扫描一次 SQL 把候选用户与「最近 user 消息时间」「open handoff」一起取出，
  避免 N+1。其余字段（如 ``has_meaningful_memory``）目前简单近似为
  ``user_profiles.preferences IS NOT NULL OR interests IS NOT NULL``，避免再发
  一次 memories 查询；spec 允许 D3 引用 profile 偏好，本期对齐。
- 频次/dedupe 仍按 D6-4 spec 在写入前做最低限度校验：每个 user 在该 tier + 本地
  日期组合下只插一次（防止同一扫描内对同一用户两次入库）。**真正的频次门**
  以 ``/api/v1/notifications/schedule`` 现有逻辑为权威，但本期 runner 直接 INSERT，
  所以我们在本函数里复刻最关键的去重 SQL（``payload->>'dedupe_key'``）。
- 任何单用户级别错误只 warning，不中断整批。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from services.silent_reactivation import (
    EligibilityResult,
    evaluate_user,
)

# 候选窗口：最近 user 消息处于 24h ~ 9d 范围内的用户
CANDIDATE_HOURS_MIN = 24
CANDIDATE_HOURS_MAX = 24 * 9
CANDIDATE_LIMIT = 200


@dataclass
class ScanSummary:
    candidates: int = 0
    created: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    created_ids: list[str] = field(default_factory=list)

    def bump_skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "created": self.created,
            "skipped": dict(self.skipped),
            "created_ids": list(self.created_ids),
        }


async def run_silent_reactivation_scan(
    db: AsyncSession,
    *,
    now_utc: datetime | None = None,
    trace_id: str | None = None,
) -> ScanSummary:
    """扫描一次候选用户并尽量创建 silent_reactivation notification_tasks。

    返回 ``ScanSummary``，无论 enable=False 还是无候选都返回（counts=0）。
    """
    summary = ScanSummary()
    log = logger.bind(
        trace_id=trace_id,
        component="silent_reactivation",
    )

    if not settings.SILENT_REACTIVATION_ENABLED:
        log.info("silent_reactivation.disabled")
        return summary

    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    log.bind(now_utc=now_utc.isoformat()).info("silent_reactivation.scan.start")

    bot_token_present = bool(getattr(settings, "TELEGRAM_BOT_TOKEN", None))

    candidates = await _fetch_candidates(db, now_utc=now_utc)
    summary.candidates = len(candidates)
    log.bind(candidate_count=len(candidates)).info("silent_reactivation.candidates_loaded")

    for row in candidates:
        user_id = str(row["id"])
        try:
            prior_tiers = await _fetch_prior_tiers(db, user_id=user_id, days=14)
            naive_last = row.get("last_user_message_at")
            last_user_message_at = (
                naive_last.replace(tzinfo=timezone.utc)
                if isinstance(naive_last, datetime) and naive_last.tzinfo is None
                else naive_last
            )

            result: EligibilityResult = evaluate_user(
                row,
                now_utc=now_utc,
                last_user_message_at=last_user_message_at,
                has_open_handoff=bool(row.get("open_handoff_count", 0)),
                has_meaningful_memory=bool(row.get("has_memory_signal")),
                telegram_bot_token_present=bot_token_present,
                prior_tiers_sent=prior_tiers,
            )
        except Exception as exc:  # pragma: no cover - 防御
            log.bind(user_id=user_id, error_type=type(exc).__name__).warning(
                "silent_reactivation.evaluate_failed"
            )
            summary.bump_skip("evaluate_exception")
            continue

        if not result.ok:
            summary.bump_skip(result.skip_reason or "unknown")
            log.bind(
                user_id=user_id,
                skip_reason=result.skip_reason,
            ).info("silent_reactivation.skip")
            continue

        # 写入 notification_tasks（含 dedupe 防同日重复）
        try:
            created_id = await _insert_task_if_absent(
                db,
                user_id=user_id,
                scheduled_at=result.scheduled_at,
                payload=result.payload or {},
            )
        except Exception as exc:
            log.bind(user_id=user_id, error_type=type(exc).__name__).warning(
                "silent_reactivation.insert_failed"
            )
            summary.bump_skip("insert_exception")
            continue

        if created_id is None:
            summary.bump_skip("duplicate_dedupe_key")
            log.bind(
                user_id=user_id,
                dedupe_key=result.dedupe_key,
            ).info("silent_reactivation.skip_duplicate")
            continue

        summary.created += 1
        summary.created_ids.append(created_id)
        log.bind(
            user_id=user_id,
            notification_id=created_id,
            tier=result.tier,
            scheduled_at=result.scheduled_at.isoformat() if result.scheduled_at else None,
            dedupe_key=result.dedupe_key,
        ).info("silent_reactivation.task_created")

    log.bind(**summary.as_dict()).info("silent_reactivation.scan.complete")
    return summary


# ── SQL helpers ───────────────────────────────────────


async def _fetch_candidates(
    db: AsyncSession,
    *,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    """取候选用户：最近 user 消息在 24h..9d 范围内、channel=telegram、状态合规。

    JOIN 一次拿够：
    - 最近 user 消息时间
    - 是否有 open handoff
    - 是否有 memory 信号（profile preferences/interests 任一非空，作为 D3 引用源近似）
    """
    rows = (
        await db.execute(
            text(
                """
                WITH last_msg AS (
                    SELECT c.user_id, MAX(m.created_at) AS last_user_message_at
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.sender_type = 'user'
                    GROUP BY c.user_id
                ),
                open_hf AS (
                    SELECT user_id, COUNT(*) AS open_handoff_count
                    FROM handoff_tasks
                    WHERE closed_at IS NULL
                      AND status IN ('pending', 'PENDING', 'ESCALATED', 'HUMAN_LOCKED')
                    GROUP BY user_id
                ),
                mem_signal AS (
                    SELECT user_id,
                           (preferences IS NOT NULL AND preferences::text NOT IN ('null', '{}'))
                        OR (interests   IS NOT NULL AND interests::text   NOT IN ('null', '[]'))
                           AS has_memory_signal
                    FROM user_profiles
                )
                SELECT
                    u.id, u.channel, u.status, u.notification_opt_in,
                    u.opt_out_marketing, u.is_minor_suspected, u.risk_level,
                    u.timezone,
                    up.relationship_stage,
                    lm.last_user_message_at,
                    COALESCE(oh.open_handoff_count, 0)   AS open_handoff_count,
                    COALESCE(ms.has_memory_signal, FALSE) AS has_memory_signal
                FROM users u
                JOIN last_msg lm ON lm.user_id = u.id
                LEFT JOIN open_hf oh ON oh.user_id = u.id
                LEFT JOIN mem_signal ms ON ms.user_id = u.id
                WHERE u.channel = 'telegram'
                  AND u.status = 'active'
                  AND u.notification_opt_in = TRUE
                  AND u.opt_out_marketing = FALSE
                  AND u.is_minor_suspected = FALSE
                  AND u.risk_level NOT IN ('high', 'critical')
                  AND COALESCE(up.relationship_stage, 'S0') <> 'S5'
                  AND lm.last_user_message_at <= :max_seen
                  AND lm.last_user_message_at >= :min_seen
                ORDER BY lm.last_user_message_at ASC
                LIMIT :limit
                """
            ),
            {
                "max_seen": _naive_utc(now_utc) - _hours(CANDIDATE_HOURS_MIN),
                "min_seen": _naive_utc(now_utc) - _hours(CANDIDATE_HOURS_MAX),
                "limit": CANDIDATE_LIMIT,
            },
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _fetch_prior_tiers(
    db: AsyncSession,
    *,
    user_id: str,
    days: int = 14,
) -> set[str]:
    """返回最近 ``days`` 天内已对该用户发送/排队过的 silent_reactivation tier 集合。"""
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT payload->>'tier' AS tier
                FROM notification_tasks
                WHERE user_id = :uid
                  AND notification_type = 'silent_reactivation'
                  AND status IN ('pending', 'sending', 'sent')
                  AND created_at >= NOW() - (:days || ' days')::INTERVAL
                """
            ),
            {"uid": user_id, "days": days},
        )
    ).mappings().all()
    return {r["tier"] for r in rows if r["tier"]}


async def _insert_task_if_absent(
    db: AsyncSession,
    *,
    user_id: str,
    scheduled_at: datetime | None,
    payload: dict[str, Any],
) -> str | None:
    """检查 dedupe_key 已存在则跳过；否则插入并返回新 id。"""
    dedupe_key = payload.get("dedupe_key")
    existing = (
        await db.execute(
            text(
                """
                SELECT 1
                FROM notification_tasks
                WHERE user_id = :uid
                  AND notification_type = 'silent_reactivation'
                  AND payload ->> 'dedupe_key' = :dedupe_key
                  AND status IN ('pending', 'sending', 'sent')
                LIMIT 1
                """
            ),
            {"uid": user_id, "dedupe_key": dedupe_key},
        )
    ).fetchone()
    if existing:
        return None

    task_id = str(uuid.uuid4())
    naive_sched = (
        scheduled_at.replace(tzinfo=None)
        if isinstance(scheduled_at, datetime) and scheduled_at.tzinfo is not None
        else scheduled_at
    )
    await db.execute(
        text(
            """
            INSERT INTO notification_tasks
                (id, user_id, channel, notification_type, payload, scheduled_at, status)
            VALUES
                (:id, :uid, 'telegram', 'silent_reactivation',
                 CAST(:payload AS jsonb), :scheduled_at, 'pending')
            """
        ),
        {
            "id": task_id,
            "uid": user_id,
            "payload": json.dumps(payload, ensure_ascii=False),
            "scheduled_at": naive_sched,
        },
    )
    await db.commit()
    return task_id


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _hours(h: int) -> Any:
    """SQLAlchemy 不接受 timedelta 直接拼到字符串，给 ``timedelta(hours=h)`` 包一层。"""
    from datetime import timedelta

    return timedelta(hours=h)
