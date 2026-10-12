"""Fast /admin/data panels: nurture + TG account reception.

These queries used to run inside the giant /attribution/summary payload,
blocking the page. They are now independent, cached, and rewritten to avoid
correlated EXISTS and a 358-account join onto message detail rows.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis import get_redis

logger = logging.getLogger(__name__)

PANEL_CACHE_TTL_SECONDS = 45
PANEL_STALE_CACHE_TTL_SECONDS = 60 * 60
PANEL_QUERY_TIMEOUT_MS = 60_000
PANEL_LOCK_TTL_SECONDS = 75
NURTURE_CACHE_KEY = "admin:data:nurture:v1"

NURTURE_SQL = """
WITH running AS (
    SELECT
        ms.id,
        ms.user_id::uuid AS user_id,
        NULLIF(ms.metadata->>'conversation_id', '')::uuid AS conversation_id,
        ms.status,
        ms.failure_reason,
        ms.created_at,
        ms.send_at,
        ms.sent_at
    FROM message_schedules ms
    WHERE ms.metadata->>'delivery_mode' = 'app_download_nurture'
      AND COALESCE(ms.metadata->>'nurture_kind', '') = 'video_chat'
      AND ms.status IN ('pending', 'sending', 'scheduled')
),
recent AS (
    SELECT
        ms.id,
        ms.user_id::uuid AS user_id,
        NULLIF(ms.metadata->>'conversation_id', '')::uuid AS conversation_id,
        ms.status,
        ms.failure_reason,
        ms.created_at,
        ms.send_at,
        ms.sent_at
    FROM message_schedules ms
    WHERE ms.metadata->>'delivery_mode' = 'app_download_nurture'
      AND COALESCE(ms.metadata->>'nurture_kind', '') = 'video_chat'
      AND ms.status NOT IN ('pending', 'sending', 'scheduled')
      AND COALESCE(ms.sent_at, ms.send_at, ms.created_at) >= NOW() - INTERVAL '7 days'
),
base AS MATERIALIZED (
    SELECT * FROM running
    UNION ALL
    SELECT * FROM recent
),
base_users AS MATERIALIZED (
    SELECT
        b.*,
        CASE
            WHEN b.created_at - (u.created_at AT TIME ZONE 'UTC') <= INTERVAL '24 hours'
            THEN 'new'
            ELSE 'old'
        END AS user_bucket
    FROM base b
    JOIN users u ON u.id = b.user_id
),
replies AS MATERIALIZED (
    SELECT DISTINCT b.id
    FROM base_users b
    INNER JOIN messages m
      ON m.conversation_id = b.conversation_id
     AND m.sender_type = 'user'
     AND b.sent_at IS NOT NULL
     AND (m.created_at AT TIME ZONE 'UTC') > b.sent_at
),
calls AS MATERIALIZED (
    SELECT
        b.id,
        BOOL_OR(TRUE) AS has_call_after_sent,
        BOOL_OR(j.status = 'completed') AS has_completed_call_after_sent
    FROM base_users b
    INNER JOIN call_broadcast_jobs j
      ON j.user_id = b.user_id::text
     AND b.sent_at IS NOT NULL
     AND j.created_at > b.sent_at
    GROUP BY b.id
),
enriched AS MATERIALIZED (
    SELECT
        b.*,
        (r.id IS NOT NULL) AS has_reply_after_sent,
        COALESCE(c.has_call_after_sent, FALSE) AS has_call_after_sent,
        COALESCE(c.has_completed_call_after_sent, FALSE) AS has_completed_call_after_sent,
        (
            COALESCE(b.failure_reason, '') ~*
            '(account_pool|send_failed|telegram|mtproto|peer|access_hash|flood|rpc|network|timeout)'
        ) AS is_technical_failure
    FROM base_users b
    LEFT JOIN replies r ON r.id = b.id
    LEFT JOIN calls c ON c.id = b.id
),
user_rollup AS MATERIALIZED (
    SELECT
        user_bucket,
        user_id,
        COUNT(*) AS scheduled_tasks,
        COUNT(*) FILTER (WHERE status = 'sent') AS sent_tasks,
        COUNT(*) FILTER (WHERE status IN ('pending', 'sending', 'scheduled')) AS running_tasks,
        COUNT(*) FILTER (WHERE status = 'failed') AS failed_tasks,
        BOOL_OR(status = 'sent') AS executed,
        BOOL_OR(status IN ('pending', 'sending', 'scheduled')) AS running,
        BOOL_OR(has_reply_after_sent) AS replied_after_sent,
        BOOL_OR(has_call_after_sent) AS called_after_sent,
        BOOL_OR(has_completed_call_after_sent) AS completed_call_after_sent,
        BOOL_OR(status = 'failed' AND is_technical_failure) AS technical_failed,
        BOOL_OR(status = 'failed' AND NOT is_technical_failure) AS stopped_after_complete
    FROM enriched
    GROUP BY user_bucket, user_id
)
SELECT json_build_object(
    'buckets', (
        SELECT COALESCE(json_agg(row_to_json(bucket_rows) ORDER BY bucket_rows.user_bucket), '[]'::json)
        FROM (
            SELECT
                user_bucket,
                COUNT(*) AS target_users,
                COUNT(*) FILTER (WHERE executed) AS executed_users,
                COUNT(*) FILTER (WHERE running) AS running_users,
                COUNT(*) FILTER (WHERE NOT running AND executed) AS completed_users,
                COUNT(*) FILTER (WHERE replied_after_sent) AS replied_users,
                COUNT(*) FILTER (WHERE called_after_sent) AS called_users,
                COUNT(*) FILTER (WHERE completed_call_after_sent) AS successful_video_users,
                COUNT(*) FILTER (WHERE technical_failed) AS failed_users,
                COUNT(*) FILTER (WHERE stopped_after_complete) AS stopped_users,
                COALESCE(SUM(scheduled_tasks), 0) AS scheduled_tasks,
                COALESCE(SUM(sent_tasks), 0) AS sent_tasks,
                COALESCE(SUM(running_tasks), 0) AS running_tasks,
                COALESCE(SUM(failed_tasks), 0) AS failed_tasks
            FROM user_rollup
            GROUP BY user_bucket
        ) bucket_rows
    ),
    'stop_reasons', (
        SELECT COALESCE(json_agg(row_to_json(stop_rows)), '[]'::json)
        FROM (
            SELECT
                user_bucket,
                COALESCE(NULLIF(failure_reason, ''), 'unknown') AS reason,
                COUNT(DISTINCT user_id) AS users,
                COUNT(*) AS tasks
            FROM enriched
            WHERE status = 'failed'
              AND NOT is_technical_failure
            GROUP BY user_bucket, reason
            ORDER BY tasks DESC, users DESC
            LIMIT 12
        ) stop_rows
    ),
    'failure_reasons', (
        SELECT COALESCE(json_agg(row_to_json(fail_rows)), '[]'::json)
        FROM (
            SELECT
                user_bucket,
                COALESCE(NULLIF(failure_reason, ''), 'unknown') AS reason,
                COUNT(DISTINCT user_id) AS users,
                COUNT(*) AS tasks
            FROM enriched
            WHERE status = 'failed'
              AND is_technical_failure
            GROUP BY user_bucket, reason
            ORDER BY tasks DESC, users DESC
            LIMIT 12
        ) fail_rows
    )
) AS payload
"""


def telegram_accounts_sql(event_window: str, call_window: str) -> str:
    return f"""
        WITH account_inbound_first AS MATERIALIZED (
            SELECT
                m.telegram_account_id::text AS account_id,
                c.user_id,
                MIN(m.created_at) AS first_inbound_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN users u ON u.id = c.user_id AND u.channel = 'telegram_real_user'
            WHERE m.sender_type = 'user'
              AND m.telegram_account_id IS NOT NULL
              AND c.user_id IS NOT NULL
            GROUP BY m.telegram_account_id, c.user_id
        ), account_user_stats AS MATERIALIZED (
            SELECT
                aif.account_id,
                COUNT(*) AS new_users_total,
                COUNT(*) FILTER (
                    WHERE aif.first_inbound_at >= :today_start
                      AND aif.first_inbound_at < :today_end
                ) AS new_users_today,
                COUNT(*) FILTER (
                    WHERE aif.first_inbound_at >= (:today_start - INTERVAL '1 day')
                      AND aif.first_inbound_at < :today_start
                ) AS new_users_yesterday,
                COUNT(*) FILTER (
                    WHERE aif.first_inbound_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - INTERVAL '30 minutes'
                      AND aif.first_inbound_at < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                ) AS new_users_last_30m
            FROM account_inbound_first aif
            GROUP BY aif.account_id
        ), assistant_stats AS MATERIALIZED (
            SELECT
                m.sender_id AS account_id,
                COUNT(DISTINCT u.id) AS served_users,
                COUNT(m.id) AS assistant_messages,
                MAX(m.created_at) AS last_message_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN users u ON u.id = c.user_id AND u.channel = 'telegram_real_user'
            WHERE m.sender_type = 'assistant'
              AND {event_window.replace("created_at", "m.created_at")}
            GROUP BY m.sender_id
        ), video_stats AS MATERIALIZED (
            SELECT
                account_id,
                COUNT(DISTINCT chat_id) FILTER (WHERE chat_id IS NOT NULL) AS video_call_users,
                COUNT(*) FILTER (WHERE status = 'completed') AS video_call_completed
            FROM call_broadcast_jobs j
            WHERE {call_window}
            GROUP BY account_id
        )
        SELECT
            ta.id::text AS account_id,
            COALESCE(NULLIF(ta.username, ''), ta.phone, ta.id::text) AS account_label,
            COALESCE(
                NULLIF(ta.metadata->>'admin_display_name', ''),
                CASE
                    WHEN NULLIF(ta.display_name, '') IS NOT NULL
                     AND char_length(ta.display_name) <= 32
                     AND ta.display_name !~ '[💋👅🍑🥺💦🔥]'
                     AND ta.display_name NOT ILIKE '%add me%'
                     AND ta.display_name NOT ILIKE '%tiktok%'
                     AND ta.display_name NOT ILIKE '%cam%'
                     AND (
                         ta.username IS NULL
                         OR lower(ta.display_name) <> lower(ta.username)
                     )
                    THEN ta.display_name
                    ELSE NULL
                END
            ) AS admin_display_name,
            ta.phone,
            ta.username,
            NULLIF(ta.display_name, '') AS telegram_profile_name,
            COALESCE(asst.served_users, 0) AS served_users,
            COALESCE(un.new_users_today, 0) AS new_users_today,
            COALESCE(un.new_users_yesterday, 0) AS new_users_yesterday,
            COALESCE(un.new_users_total, 0) AS new_users_total,
            COALESCE(un.new_users_last_30m, 0) AS new_users_last_30m,
            COALESCE(asst.assistant_messages, 0) AS assistant_messages,
            asst.last_message_at,
            COALESCE(vc.video_call_users, 0) AS video_call_users,
            COALESCE(vc.video_call_completed, 0) AS video_call_completed
        FROM telegram_accounts ta
        LEFT JOIN account_user_stats un ON un.account_id = ta.id::text
        LEFT JOIN assistant_stats asst ON asst.account_id = ta.id::text
        LEFT JOIN video_stats vc ON vc.account_id = ta.id
        WHERE ta.status = 'connected'
          AND ta.is_active = TRUE
          AND COALESCE((ta.metadata->>'archived_deleted')::boolean, FALSE) = FALSE
        ORDER BY
            COALESCE(un.new_users_last_30m, 0) DESC,
            asst.last_message_at DESC NULLS LAST,
            account_label ASC
    """


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _loads_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def format_nurture_payload(raw: Any) -> dict[str, Any]:
    payload = _loads_json(raw) or {}
    buckets_in = payload.get("buckets") or []
    return {
        "buckets": [
            {
                "bucket": row.get("user_bucket") or row.get("bucket") or "old",
                "label": (
                    "新用户培育"
                    if (row.get("user_bucket") or row.get("bucket")) == "new"
                    else "老用户培育"
                ),
                "target_users": _as_int(row.get("target_users")),
                "executed_users": _as_int(row.get("executed_users")),
                "running_users": _as_int(row.get("running_users")),
                "completed_users": _as_int(row.get("completed_users")),
                "replied_users": _as_int(row.get("replied_users")),
                "called_users": _as_int(row.get("called_users")),
                "successful_video_users": _as_int(row.get("successful_video_users")),
                "failed_users": _as_int(row.get("failed_users")),
                "stopped_users": _as_int(row.get("stopped_users")),
                "scheduled_tasks": _as_int(row.get("scheduled_tasks")),
                "sent_tasks": _as_int(row.get("sent_tasks")),
                "running_tasks": _as_int(row.get("running_tasks")),
                "failed_tasks": _as_int(row.get("failed_tasks")),
                "reply_rate": _rate(_as_int(row.get("replied_users")), _as_int(row.get("executed_users"))),
                "call_rate": _rate(_as_int(row.get("called_users")), _as_int(row.get("executed_users"))),
                "successful_video_rate": _rate(
                    _as_int(row.get("successful_video_users")),
                    _as_int(row.get("executed_users")),
                ),
            }
            for row in buckets_in
        ],
        "stop_reasons": [
            {
                "bucket": row.get("user_bucket") or row.get("bucket") or "old",
                "reason": row.get("reason") or "unknown",
                "users": _as_int(row.get("users")),
                "tasks": _as_int(row.get("tasks")),
            }
            for row in (payload.get("stop_reasons") or [])
        ],
        "failure_reasons": [
            {
                "bucket": row.get("user_bucket") or row.get("bucket") or "old",
                "reason": row.get("reason") or "unknown",
                "users": _as_int(row.get("users")),
                "tasks": _as_int(row.get("tasks")),
            }
            for row in (payload.get("failure_reasons") or [])
        ],
    }


def format_telegram_account_row(row: Any) -> dict[str, Any]:
    last_message_at = row[12] if len(row) > 12 else None
    if hasattr(last_message_at, "isoformat"):
        last_message_at = last_message_at.isoformat()
    return {
        "account_id": row[0] or "",
        "account_label": row[1] or "unknown",
        "admin_display_name": row[2],
        "phone": row[3],
        "username": row[4],
        "telegram_profile_name": row[5],
        "served_users": _as_int(row[6]),
        "new_users_today": _as_int(row[7]),
        "new_users_yesterday": _as_int(row[8]),
        "new_users_total": _as_int(row[9]),
        "new_users_last_30m": _as_int(row[10]),
        "assistant_messages": _as_int(row[11]),
        "last_message_at": last_message_at,
        "video_call_users": _as_int(row[13] if len(row) > 13 else 0),
        "video_call_completed": _as_int(row[14] if len(row) > 14 else 0),
    }


async def _cache_get(key: str) -> Any | None:
    try:
        redis = await get_redis()
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("admin data panel cache get failed", exc_info=True)
    return None


async def _cache_set(key: str, value: Any) -> None:
    try:
        redis = await get_redis()
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        await redis.setex(key, PANEL_CACHE_TTL_SECONDS, encoded)
        await redis.setex(f"{key}:stale", PANEL_STALE_CACHE_TTL_SECONDS, encoded)
    except Exception:
        logger.warning("admin data panel cache set failed", exc_info=True)


@asynccontextmanager
async def _singleflight(cache_key: str):
    redis = None
    lock_key = f"{cache_key}:lock"
    acquired = False
    try:
        redis = await get_redis()
        acquired = bool(await redis.set(lock_key, "1", ex=PANEL_LOCK_TTL_SECONDS, nx=True))
    except Exception:
        logger.warning("admin data panel lock acquire failed", exc_info=True)

    if not acquired and redis is not None:
        for _ in range(PANEL_QUERY_TIMEOUT_MS // 250):
            await asyncio.sleep(0.25)
            cached = await _cache_get(cache_key)
            if cached is not None:
                yield cached
                return
            try:
                if not await redis.exists(lock_key):
                    acquired = bool(await redis.set(lock_key, "1", ex=PANEL_LOCK_TTL_SECONDS, nx=True))
                    if acquired:
                        break
            except Exception:
                break

    try:
        yield None
    finally:
        if acquired and redis is not None:
            try:
                await redis.delete(lock_key)
            except Exception:
                logger.warning("admin data panel lock release failed", exc_info=True)


async def _set_query_timeout(db: AsyncSession) -> None:
    await db.execute(text(f"SET LOCAL statement_timeout = '{PANEL_QUERY_TIMEOUT_MS}ms'"))


async def fetch_nurture_summary(db: AsyncSession) -> dict[str, Any]:
    cached = await _cache_get(NURTURE_CACHE_KEY)
    if cached is not None:
        return cached
    async with _singleflight(NURTURE_CACHE_KEY) as waited_payload:
        if waited_payload is not None:
            return waited_payload
        await _set_query_timeout(db)
        try:
            row = (await db.execute(text(NURTURE_SQL))).fetchone()
            payload = format_nurture_payload(row[0] if row else None)
        except Exception:
            await db.rollback()
            stale = await _cache_get(f"{NURTURE_CACHE_KEY}:stale")
            if stale is not None:
                logger.warning("admin nurture query failed; serving stale cache", exc_info=True)
                return stale
            logger.warning("admin nurture query failed; serving safe empty payload", exc_info=True)
            return format_nurture_payload(None)
        await _cache_set(NURTURE_CACHE_KEY, payload)
        return payload


def telegram_cache_key(params: dict[str, Any]) -> str:
    return (
        "admin:data:tg:v1:"
        f"{params.get('today_start')}:"
        f"{params.get('today_end')}:"
        f"{params.get('start_at')}:"
        f"{params.get('end_at')}"
    )


async def fetch_telegram_accounts(
    db: AsyncSession,
    params: dict[str, Any],
    event_window: str,
    call_window: str,
    *,
    bypass_cache: bool = False,
) -> list[dict[str, Any]]:
    cache_key = telegram_cache_key(params)
    if not bypass_cache:
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached
    async with _singleflight(cache_key) as waited_payload:
        if waited_payload is not None and not bypass_cache:
            return waited_payload
        await _set_query_timeout(db)
        try:
            rows = (await db.execute(text(telegram_accounts_sql(event_window, call_window)), params)).fetchall()
            payload = [format_telegram_account_row(row) for row in rows]
        except Exception:
            await db.rollback()
            stale = await _cache_get(f"{cache_key}:stale")
            if stale is not None:
                logger.warning("admin telegram panel query failed; serving stale cache", exc_info=True)
                return stale
            logger.warning("admin telegram panel query failed; serving safe empty payload", exc_info=True)
            return []
        await _cache_set(cache_key, payload)
        return payload
