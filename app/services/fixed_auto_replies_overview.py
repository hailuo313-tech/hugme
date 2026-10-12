"""Optimized SQL fetchers for fixed auto-reply admin overview."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# Cross-TG dedup: same Telegram person counts once even if they hit multiple fixed accounts.
_FIXED_PERSON_KEY_FROM_JOB_USER = """
COALESCE(
    CASE
        WHEN COALESCE(u.external_id, j.external_user_id) ~ '^tg_[0-9]+$'
        THEN 'tg:' || SUBSTRING(COALESCE(u.external_id, j.external_user_id) FROM 4)
    END,
    CASE
        WHEN NULLIF(COALESCE(u.external_id, j.external_user_id), '') IS NOT NULL
        THEN 'ext:' || COALESCE(u.external_id, j.external_user_id)
    END,
    CASE WHEN j.chat_id IS NOT NULL THEN 'tg:' || j.chat_id::text END,
    CASE WHEN u.id IS NOT NULL THEN 'uid:' || u.id::text END,
    CASE WHEN j.user_id IS NOT NULL THEN 'uid:' || j.user_id::text END
)
"""

_FIXED_PERSON_KEY_FROM_CALL_JOB = """
COALESCE(
    CASE
        WHEN COALESCE(cbj.external_user_id, u.external_id) ~ '^tg_[0-9]+$'
        THEN 'tg:' || SUBSTRING(COALESCE(cbj.external_user_id, u.external_id) FROM 4)
    END,
    CASE
        WHEN NULLIF(COALESCE(cbj.external_user_id, u.external_id), '') IS NOT NULL
        THEN 'ext:' || COALESCE(cbj.external_user_id, u.external_id)
    END,
    CASE WHEN cbj.chat_id IS NOT NULL THEN 'tg:' || cbj.chat_id::text END,
    CASE
        WHEN cbj.user_id ~ '^[0-9a-f-]{36}$' AND u.id IS NOT NULL
        THEN 'uid:' || u.id::text
    END,
    CASE
        WHEN cbj.user_id ~ '^[0-9a-f-]{36}$'
        THEN 'uid:' || cbj.user_id
    END,
    CASE
        WHEN NULLIF(cbj.user_id, '') IS NOT NULL
        THEN 'ext:' || cbj.user_id
    END
)
"""

_FIXED_LINK_PERSON_KEY = """
COALESCE(
    CASE
        WHEN COALESCE(u.external_id, '') ~ '^tg_[0-9]+$'
        THEN 'tg:' || SUBSTRING(u.external_id FROM 4)
    END,
    CASE
        WHEN NULLIF(u.external_id, '') IS NOT NULL
        THEN 'ext:' || u.external_id
    END,
    CAST({user_ref} AS text)
)
"""

_OVERVIEW_PERIOD_CTES = f"""                beijing_clock AS (
                    SELECT timezone('Asia/Shanghai', NOW()) AS now_bj
                ),
                period_local AS (
                    SELECT
                        CASE
                            WHEN :target_date IS NOT NULL THEN CAST(:target_date AS date)::timestamp
                            WHEN :range_key = 'yesterday' THEN date_trunc('day', now_bj) - interval '1 day'
                            WHEN :range_key = 'week' THEN date_trunc('week', now_bj)
                            WHEN :range_key = 'month' THEN date_trunc('month', now_bj)
                            ELSE date_trunc('day', now_bj)
                        END AS start_local,
                        CASE
                            WHEN :target_date IS NOT NULL THEN (CAST(:target_date AS date) + 1)::timestamp
                            WHEN :range_key = 'yesterday' THEN date_trunc('day', now_bj)
                            WHEN :range_key = 'week' THEN date_trunc('week', now_bj) + interval '1 week'
                            WHEN :range_key = 'month' THEN date_trunc('month', now_bj) + interval '1 month'
                            ELSE date_trunc('day', now_bj) + interval '1 day'
                        END AS end_local
                    FROM beijing_clock
                ),
                selected_period AS (
                    SELECT
                        start_local AT TIME ZONE 'Asia/Shanghai' AS start_at,
                        end_local AT TIME ZONE 'Asia/Shanghai' AS end_at,
                        (start_local AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'UTC' AS start_naive,
                        (end_local AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'UTC' AS end_naive
                    FROM period_local
                ),
                fixed_accounts AS (
                    SELECT id
                    FROM telegram_accounts
                    WHERE COALESCE(metadata->>'reply_mode', 'ai') = 'fixed'
                      AND is_active IS TRUE
                      AND COALESCE(status, '') <> 'banned'
                ),
                fixed_link_received_users_period AS (
                    SELECT DISTINCT user_key
                    FROM (
                        SELECT {_FIXED_LINK_PERSON_KEY.format(user_ref="COALESCE(e.user_id, l.user_id, c.user_id)")} AS user_key
                        FROM attribution_events e
                        JOIN attribution_links l ON l.tracking_id = e.tracking_id
                        JOIN fixed_accounts fa ON l.sender_account_id = fa.id::text
                        LEFT JOIN messages m ON m.id = l.message_id
                        LEFT JOIN conversations c ON c.id = COALESCE(l.conversation_id, m.conversation_id)
                        LEFT JOIN users u ON u.id = COALESCE(e.user_id, l.user_id, c.user_id)
                        CROSS JOIN selected_period p
                        WHERE e.event_type = 'link_exposed'
                          AND e.created_at >= p.start_naive
                          AND e.created_at < p.end_naive
                        UNION ALL
                        SELECT {_FIXED_PERSON_KEY_FROM_JOB_USER} AS user_key
                        FROM messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        JOIN users u ON u.id = c.user_id
                        JOIN fixed_accounts fa ON m.sender_id = fa.id::text
                        LEFT JOIN fixed_auto_reply_jobs j
                            ON j.conversation_id = c.id
                           AND j.account_id = fa.id
                        CROSS JOIN selected_period p
                        WHERE m.sender_type = 'assistant'
                          AND m.content ~* 'https?://'
                          AND m.created_at >= p.start_naive
                          AND m.created_at < p.end_naive
                    ) received
                    WHERE user_key IS NOT NULL
                ),
                fixed_link_click_users_period AS (
                    SELECT DISTINCT user_key
                    FROM (
                        SELECT {_FIXED_LINK_PERSON_KEY.format(user_ref="COALESCE(e.user_id, l.user_id)")} AS user_key
                        FROM attribution_events e
                        JOIN attribution_links l ON l.tracking_id = e.tracking_id
                        JOIN fixed_accounts fa ON l.sender_account_id = fa.id::text
                        LEFT JOIN users u ON u.id = COALESCE(e.user_id, l.user_id)
                        CROSS JOIN selected_period p
                        WHERE e.event_type = 'click'
                          AND e.created_at >= p.start_naive
                          AND e.created_at < p.end_naive
                    ) clicked
                    WHERE user_key IS NOT NULL
                )
"""


def _overview_params(range_key: str, target_date: date | None) -> dict[str, Any]:
    return {"range_key": range_key, "target_date": target_date}


def _overview_bindparams():
    return (
        bindparam("range_key", type_=String()),
        bindparam("target_date", type_=Date()),
    )


async def fetch_overview_summary(
    db: AsyncSession,
    *,
    range_key: str,
    target_date: date | None,
) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                f"""
                WITH {_OVERVIEW_PERIOD_CTES},
                fixed_jobs_touched AS (
                    SELECT j.*, u.external_id
                    FROM fixed_auto_reply_jobs j
                    JOIN fixed_accounts ta ON ta.id = j.account_id
                    LEFT JOIN users u ON u.id = j.user_id
                    CROSS JOIN selected_period p
                    WHERE (j.created_at >= p.start_at AND j.created_at < p.end_at)
                       OR (j.sent_at >= p.start_at AND j.sent_at < p.end_at)
                       OR (j.updated_at >= p.start_at AND j.updated_at < p.end_at)
                ),
                fixed_jobs_created AS (
                    SELECT j.*
                    FROM fixed_auto_reply_jobs j
                    JOIN fixed_accounts ta ON ta.id = j.account_id
                    CROSS JOIN selected_period p
                    WHERE j.created_at >= p.start_at AND j.created_at < p.end_at
                ),
                fixed_new_users_today AS (
                    SELECT person_key
                    FROM (
                        SELECT
                            {_FIXED_PERSON_KEY_FROM_JOB_USER} AS person_key,
                            MIN(u.created_at) AS first_user_created_at
                        FROM fixed_auto_reply_jobs j
                        JOIN fixed_accounts ta ON ta.id = j.account_id
                        JOIN users u ON u.id = j.user_id
                        GROUP BY {_FIXED_PERSON_KEY_FROM_JOB_USER}
                    ) persons
                    CROSS JOIN selected_period p
                    WHERE person_key IS NOT NULL
                      AND first_user_created_at >= p.start_naive
                      AND first_user_created_at < p.end_naive
                ),
                fixed_replies_today AS (
                    SELECT DISTINCT {_FIXED_PERSON_KEY_FROM_JOB_USER} AS person_key
                    FROM fixed_auto_reply_jobs j
                    JOIN fixed_accounts ta ON ta.id = j.account_id
                    JOIN users u ON u.id = j.user_id
                    JOIN messages m ON m.conversation_id = j.conversation_id
                    CROSS JOIN selected_period p
                    WHERE m.sender_type = 'user'
                      AND m.created_at >= p.start_naive
                      AND m.created_at < p.end_naive
                      AND (j.sent_at IS NULL OR m.created_at >= j.sent_at)
                ),
                fixed_calls_today AS (
                    SELECT cbj.*, u.external_id
                    FROM call_broadcast_jobs cbj
                    JOIN fixed_accounts ta ON ta.id = cbj.account_id
                    LEFT JOIN users u
                        ON cbj.user_id ~ '^[0-9a-f-]{{36}}$'
                       AND u.id::text = cbj.user_id
                    CROSS JOIN selected_period p
                    WHERE COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) >= p.start_at
                      AND COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) < p.end_at
                )
                SELECT
                    (SELECT COUNT(*) FROM fixed_accounts) AS fixed_account_count,
                    (SELECT COUNT(*) FROM telegram_accounts ta
                      JOIN fixed_accounts fa ON fa.id = ta.id
                      WHERE ta.status = 'connected') AS connected_fixed_account_count,
                    (SELECT COUNT(*) FROM fixed_auto_reply_rules) AS total_rule_count,
                    (SELECT COUNT(*) FROM fixed_auto_reply_rules WHERE is_active = TRUE) AS active_rule_count,
                    (
                        SELECT COUNT(DISTINCT {_FIXED_PERSON_KEY_FROM_JOB_USER})
                        FROM fixed_jobs_touched j
                        LEFT JOIN users u ON u.id = j.user_id
                    ) AS today_touched_users,
                    (SELECT COUNT(*) FROM fixed_jobs_created) AS today_generated_jobs,
                    (
                        SELECT COUNT(*)
                        FROM fixed_auto_reply_jobs j
                        JOIN fixed_accounts ta ON ta.id = j.account_id
                        CROSS JOIN selected_period p
                        WHERE j.status = 'sent'
                          AND j.sent_at >= p.start_at
                          AND j.sent_at < p.end_at
                    ) AS today_sent_jobs,
                    (
                        SELECT COUNT(*)
                        FROM fixed_auto_reply_jobs j
                        JOIN fixed_accounts ta ON ta.id = j.account_id
                        WHERE j.status = 'pending'
                    ) AS today_pending_jobs,
                    (
                        SELECT COUNT(*)
                        FROM fixed_auto_reply_jobs j
                        JOIN fixed_accounts ta ON ta.id = j.account_id
                        CROSS JOIN selected_period p
                        WHERE j.status = 'failed'
                          AND j.updated_at >= p.start_at
                          AND j.updated_at < p.end_at
                    ) AS today_failed_jobs,
                    (
                        SELECT COUNT(*)
                        FROM fixed_auto_reply_jobs j
                        JOIN fixed_accounts ta ON ta.id = j.account_id
                        CROSS JOIN selected_period p
                        WHERE j.status = 'skipped'
                          AND j.updated_at >= p.start_at
                          AND j.updated_at < p.end_at
                    ) AS today_skipped_jobs,
                    (SELECT COUNT(*) FROM fixed_new_users_today) AS today_new_users,
                    (SELECT COUNT(*) FROM fixed_replies_today WHERE person_key IS NOT NULL) AS today_reply_users,
                    (
                        SELECT COUNT(DISTINCT {_FIXED_PERSON_KEY_FROM_CALL_JOB})
                        FROM fixed_calls_today cbj
                        LEFT JOIN users u
                            ON cbj.user_id ~ '^[0-9a-f-]{{36}}$'
                           AND u.id::text = cbj.user_id
                    ) AS today_video_users,
                    (
                        SELECT COUNT(DISTINCT {_FIXED_PERSON_KEY_FROM_CALL_JOB})
                        FROM fixed_calls_today cbj
                        LEFT JOIN users u
                            ON cbj.user_id ~ '^[0-9a-f-]{{36}}$'
                           AND u.id::text = cbj.user_id
                        WHERE cbj.status = 'completed'
                    ) AS today_video_success_users,
                    (SELECT COUNT(*) FROM fixed_link_received_users_period) AS today_link_received_users,
                    (SELECT COUNT(*) FROM fixed_link_click_users_period) AS today_link_click_users
                """
            ).bindparams(*_overview_bindparams()),
            _overview_params(range_key, target_date),
        )
    ).mappings().first()
    return dict(row) if row else {}


async def fetch_overview_accounts(
    db: AsyncSession,
    *,
    range_key: str,
    target_date: date | None,
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            f"""
            WITH {_OVERVIEW_PERIOD_CTES},
            period_jobs AS (
                SELECT j.*, p.start_at, p.end_at, p.start_naive, p.end_naive
                FROM fixed_auto_reply_jobs j
                JOIN fixed_accounts fa ON fa.id = j.account_id
                CROSS JOIN selected_period p
                WHERE (j.created_at >= p.start_at AND j.created_at < p.end_at)
                   OR (j.sent_at >= p.start_at AND j.sent_at < p.end_at)
                   OR (j.updated_at >= p.start_at AND j.updated_at < p.end_at)
            ),
            account_job_stats AS (
                SELECT
                    j.account_id,
                    COUNT(DISTINCT j.user_id) AS touched_users,
                    COUNT(DISTINCT j.user_id) FILTER (
                        WHERE u.created_at >= j.start_naive AND u.created_at < j.end_naive
                    ) AS new_users,
                    COUNT(*) FILTER (
                        WHERE j.status = 'sent'
                          AND j.sent_at >= j.start_at
                          AND j.sent_at < j.end_at
                    ) AS sent_jobs,
                    COUNT(*) FILTER (
                        WHERE j.status = 'failed'
                          AND j.updated_at >= j.start_at
                          AND j.updated_at < j.end_at
                    ) AS failed_jobs
                FROM period_jobs j
                LEFT JOIN users u ON u.id = j.user_id
                GROUP BY j.account_id
            ),
            account_reply_stats AS (
                SELECT j.account_id, COUNT(DISTINCT j.user_id) AS reply_users
                FROM fixed_auto_reply_jobs j
                JOIN fixed_accounts fa ON fa.id = j.account_id
                JOIN messages m ON m.conversation_id = j.conversation_id
                CROSS JOIN selected_period p
                WHERE m.sender_type = 'user'
                  AND m.created_at >= p.start_naive
                  AND m.created_at < p.end_naive
                  AND (j.sent_at IS NULL OR m.created_at >= j.sent_at)
                GROUP BY j.account_id
            ),
            account_call_stats AS (
                SELECT
                    cbj.account_id,
                    COUNT(DISTINCT COALESCE(cbj.user_id::text, cbj.external_user_id, cbj.chat_id::text)) AS video_users,
                    COUNT(*) AS video_calls,
                    COUNT(*) FILTER (WHERE cbj.status = 'completed') AS video_success
                FROM call_broadcast_jobs cbj
                JOIN fixed_accounts fa ON fa.id = cbj.account_id
                CROSS JOIN selected_period p
                WHERE COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) >= p.start_at
                  AND COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) < p.end_at
                GROUP BY cbj.account_id
            )
            SELECT
                ta.id::text AS id,
                ta.phone,
                ta.display_name,
                ta.username,
                ta.status,
                ta.is_active,
                ta.last_connected_at,
                ta.error_message,
                COALESCE(ajs.new_users, 0) AS today_new_users,
                COALESCE(ajs.touched_users, 0) AS today_touched_users,
                COALESCE(ajs.sent_jobs, 0) AS today_sent_jobs,
                COALESCE(ajs.failed_jobs, 0) AS today_failed_jobs,
                COALESCE(ars.reply_users, 0) AS today_reply_users,
                COALESCE(acs.video_users, 0) AS today_video_users,
                COALESCE(acs.video_calls, 0) AS today_video_calls,
                COALESCE(acs.video_success, 0) AS today_video_success
            FROM telegram_accounts ta
            JOIN fixed_accounts fa ON fa.id = ta.id
            LEFT JOIN account_job_stats ajs ON ajs.account_id = ta.id
            LEFT JOIN account_reply_stats ars ON ars.account_id = ta.id
            LEFT JOIN account_call_stats acs ON acs.account_id = ta.id
            ORDER BY ta.last_connected_at DESC NULLS LAST, ta.created_at DESC
            """
        ).bindparams(*_overview_bindparams()),
        _overview_params(range_key, target_date),
    )
    return [dict(row._mapping) for row in rows.fetchall()]


async def fetch_overview_rules(
    db: AsyncSession,
    *,
    range_key: str,
    target_date: date | None,
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            f"""
            WITH {_OVERVIEW_PERIOD_CTES},
            period_jobs AS (
                SELECT j.*, p.start_at, p.end_at, p.start_naive, p.end_naive
                FROM fixed_auto_reply_jobs j
                JOIN fixed_accounts fa ON fa.id = j.account_id
                CROSS JOIN selected_period p
                WHERE (j.created_at >= p.start_at AND j.created_at < p.end_at)
                   OR (j.sent_at >= p.start_at AND j.sent_at < p.end_at)
                   OR (j.updated_at >= p.start_at AND j.updated_at < p.end_at)
            ),
            job_stats AS (
                SELECT
                    j.rule_id,
                    COUNT(DISTINCT j.user_id) AS total_users,
                    COUNT(DISTINCT j.user_id) FILTER (
                        WHERE j.status = 'sent'
                          AND j.sent_at >= j.start_at
                          AND j.sent_at < j.end_at
                    ) AS sent_users,
                    COUNT(*) FILTER (WHERE j.status = 'pending') AS pending_jobs,
                    COUNT(*) FILTER (
                        WHERE j.status = 'failed'
                          AND j.updated_at >= j.start_at
                          AND j.updated_at < j.end_at
                    ) AS failed_jobs
                FROM period_jobs j
                GROUP BY j.rule_id
            ),
            reply_stats AS (
                SELECT j.rule_id, COUNT(DISTINCT j.user_id) AS reply_users
                FROM period_jobs j
                JOIN messages m ON m.conversation_id = j.conversation_id
                WHERE m.sender_type = 'user'
                  AND m.created_at >= j.start_naive
                  AND m.created_at < j.end_naive
                  AND (j.sent_at IS NULL OR m.created_at >= j.sent_at)
                GROUP BY j.rule_id
            ),
            video_stats AS (
                SELECT
                    j.rule_id,
                    COUNT(DISTINCT j.user_id) AS video_users,
                    COUNT(DISTINCT j.user_id) FILTER (WHERE cbj.status = 'completed') AS video_success_users
                FROM period_jobs j
                JOIN call_broadcast_jobs cbj ON cbj.account_id = j.account_id
                  AND (
                      cbj.user_id = j.user_id::text
                      OR cbj.external_user_id = j.external_user_id
                      OR cbj.chat_id = j.chat_id
                  )
                WHERE COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) >= j.start_at
                  AND COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) < j.end_at
                  AND (j.sent_at IS NULL OR COALESCE(cbj.ended_at, cbj.started_at, cbj.created_at) >= j.sent_at)
                GROUP BY j.rule_id
            )
            SELECT
                r.id::text AS id,
                r.name,
                r.delay_seconds,
                r.is_active,
                COALESCE(js.total_users, 0) AS total_users,
                COALESCE(js.sent_users, 0) AS sent_users,
                COALESCE(js.pending_jobs, 0) AS pending_jobs,
                COALESCE(js.failed_jobs, 0) AS failed_jobs,
                COALESCE(rs.reply_users, 0) AS reply_users,
                COALESCE(vs.video_users, 0) AS video_users,
                COALESCE(vs.video_success_users, 0) AS video_success_users
            FROM fixed_auto_reply_rules r
            LEFT JOIN job_stats js ON js.rule_id = r.id
            LEFT JOIN reply_stats rs ON rs.rule_id = r.id
            LEFT JOIN video_stats vs ON vs.rule_id = r.id
            ORDER BY r.sort_order ASC, r.created_at ASC, r.id ASC
            """
        ).bindparams(*_overview_bindparams()),
        _overview_params(range_key, target_date),
    )
    return [dict(row._mapping) for row in rows.fetchall()]


async def fetch_overview_failures(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            """
            SELECT
                COALESCE(NULLIF(failure_reason, ''), 'unknown') AS reason,
                COUNT(*) AS count,
                MAX(updated_at) AS last_at
            FROM fixed_auto_reply_jobs
            WHERE status = 'failed'
            GROUP BY COALESCE(NULLIF(failure_reason, ''), 'unknown')
            ORDER BY count DESC, last_at DESC NULLS LAST
            LIMIT 8
            """
        )
    )
    return [dict(row._mapping) for row in rows.fetchall()]
