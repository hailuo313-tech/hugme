"""Standalone fixed auto-reply rules.

This module is intentionally independent from the AI/script/nurture pipeline.
Rules enqueue one delayed job per newly seen Telegram real user after the rule
is enabled, then send configured text and media in order.

Dispatch is account-fair: each connected fixed TG account receives a per-tick
batch quota so one account's backlog cannot starve the others.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import re
import uuid
from collections import defaultdict
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import text
from services.outbound_account_gate import check_outbound_account, pause_outbound_account

from core.config import settings
from core.database import AsyncSessionLocal
from services.link_attribution import (
    render_tracking_links_as_html_cta,
    wrap_text_links_with_tracking,
)
from services.mtproto.peer_resolve import resolve_telethon_peer
from services.script_asset_delivery import send_mtproto_asset
from services.telegram_account_manager import telegram_account_manager


_scheduler: AsyncIOScheduler | None = None
_schema_ready = False
_send_tick_running = False


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS fixed_auto_reply_rules (
        id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        text_content TEXT NOT NULL DEFAULT '',
        delay_seconds INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT FALSE,
        activated_at TIMESTAMPTZ NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fixed_auto_reply_assets (
        id UUID PRIMARY KEY,
        rule_id UUID NOT NULL REFERENCES fixed_auto_reply_rules(id) ON DELETE CASCADE,
        asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'video', 'voice', 'audio')),
        asset_url TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        original_filename TEXT NULL,
        mime_type TEXT NULL,
        file_size_bytes BIGINT NULL,
        caption TEXT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fixed_auto_reply_jobs (
        id UUID PRIMARY KEY,
        rule_id UUID NOT NULL REFERENCES fixed_auto_reply_rules(id) ON DELETE CASCADE,
        user_id UUID NOT NULL,
        conversation_id UUID NULL,
        external_user_id TEXT NOT NULL,
        account_id UUID NULL,
        chat_id BIGINT NULL,
        telegram_access_hash BIGINT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'skipped')),
        send_at TIMESTAMPTZ NOT NULL,
        sent_at TIMESTAMPTZ NULL,
        failure_reason TEXT NULL,
        trace_id TEXT NULL,
        send_attempts INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(rule_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fixed_auto_reply_deliveries (
        id UUID PRIMARY KEY,
        job_id UUID NOT NULL REFERENCES fixed_auto_reply_jobs(id) ON DELETE CASCADE,
        rule_id UUID NOT NULL REFERENCES fixed_auto_reply_rules(id) ON DELETE CASCADE,
        item_type TEXT NOT NULL,
        asset_id UUID NULL,
        status TEXT NOT NULL,
        error TEXT NULL,
        sent_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fixed_auto_reply_rule_recipients (
        id UUID PRIMARY KEY,
        rule_id UUID NOT NULL REFERENCES fixed_auto_reply_rules(id) ON DELETE CASCADE,
        user_id UUID NULL,
        external_user_id TEXT NOT NULL,
        first_job_id UUID NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(rule_id, external_user_id)
    )
    """,
    "ALTER TABLE fixed_auto_reply_jobs ADD COLUMN IF NOT EXISTS send_attempts INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_rules_active ON fixed_auto_reply_rules (is_active, activated_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_assets_rule ON fixed_auto_reply_assets (rule_id, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_due ON fixed_auto_reply_jobs (status, send_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_user ON fixed_auto_reply_jobs (external_user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_created ON fixed_auto_reply_jobs (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_updated ON fixed_auto_reply_jobs (updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_sent ON fixed_auto_reply_jobs (sent_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_account_created ON fixed_auto_reply_jobs (account_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_account_sent ON fixed_auto_reply_jobs (account_id, sent_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_rule_status ON fixed_auto_reply_jobs (rule_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_conversation_sent ON fixed_auto_reply_jobs (conversation_id, sent_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_account_due ON fixed_auto_reply_jobs (account_id, status, send_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_jobs_sending_updated ON fixed_auto_reply_jobs (status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_deliveries_job ON fixed_auto_reply_deliveries (job_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_deliveries_rule_created ON fixed_auto_reply_deliveries (rule_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_deliveries_status_created ON fixed_auto_reply_deliveries (status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_fixed_auto_reply_rule_recipients_external ON fixed_auto_reply_rule_recipients (external_user_id, created_at DESC)",
]


def _cfg(name: str, default: int) -> int:
    return max(1, int(getattr(settings, name, default)))


async def ensure_schema(db) -> None:
    global _schema_ready
    if _schema_ready:
        return
    for sql in SCHEMA_SQL:
        await db.execute(text(sql))
    await db.commit()
    _schema_ready = True


def start_scheduler() -> None:
    global _scheduler
    if not getattr(settings, "FIXED_AUTO_REPLY_ENABLED", True):
        return
    if _scheduler and _scheduler.running:
        return
    max_instances = max(1, int(getattr(settings, "FIXED_AUTO_REPLY_SCHEDULER_MAX_INSTANCES", 1)))
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_fixed_auto_reply_enqueue_tick,
        IntervalTrigger(seconds=_cfg("FIXED_AUTO_REPLY_ENQUEUE_POLL_SECONDS", 60)),
        id="fixed_auto_reply_enqueue_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        run_fixed_auto_reply_send_tick,
        IntervalTrigger(seconds=_cfg("FIXED_AUTO_REPLY_SEND_POLL_SECONDS", 5)),
        id="fixed_auto_reply_send_tick",
        replace_existing=True,
        max_instances=max_instances,
        coalesce=True,
    )
    _scheduler.add_job(
        run_fixed_auto_reply_recovery_tick,
        IntervalTrigger(seconds=_cfg("FIXED_AUTO_REPLY_RECOVERY_POLL_SECONDS", 60)),
        id="fixed_auto_reply_recovery_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("fixed_auto_reply.worker.started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


async def run_fixed_auto_reply_tick(trace_id: str | None = None) -> dict[str, int]:
    """Legacy combined tick; kept for admin run-once and tests."""
    trace_id = trace_id or str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await ensure_schema(db)
        enqueued = await _enqueue_new_user_jobs(db)
        await db.commit()
    recovered = await run_fixed_auto_reply_recovery_tick()
    sent, failed = await _send_due_jobs(trace_id=trace_id)
    return {
        "enqueued": enqueued,
        "sent": sent,
        "failed": failed,
        "recovered_to_pending": recovered.get("recovered_to_pending", 0),
        "marked_failed": recovered.get("marked_failed", 0),
    }


async def run_fixed_auto_reply_enqueue_tick() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        await ensure_schema(db)
        enqueued = await _enqueue_new_user_jobs(db)
        await db.commit()
    return {"enqueued": enqueued}


async def run_fixed_auto_reply_send_tick() -> dict[str, int]:
    global _send_tick_running
    if _send_tick_running:
        logger.info("fixed_auto_reply.send_tick.skip_already_running")
        return {"sent": 0, "failed": 0, "skipped": 1}
    _send_tick_running = True
    trace_id = str(uuid.uuid4())
    try:
        timeout_s = _cfg("FIXED_AUTO_REPLY_SEND_TICK_TIMEOUT_SECONDS", 90)
        sent, failed = await asyncio.wait_for(_send_due_jobs(trace_id=trace_id), timeout=timeout_s)
        return {"sent": sent, "failed": failed}
    except asyncio.TimeoutError:
        logger.bind(trace_id=trace_id).warning("fixed_auto_reply.send_tick.timeout")
        return {"sent": 0, "failed": 0, "timed_out": 1}
    finally:
        _send_tick_running = False


async def run_fixed_auto_reply_recovery_tick() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        await ensure_schema(db)
        result = await _recover_stuck_jobs(db)
        await db.commit()
    if result["recovered_to_pending"] or result["marked_failed"]:
        logger.bind(**result).info("fixed_auto_reply.recovery.completed")
    return result


async def _recover_stuck_jobs(db) -> dict[str, int]:
    timeout_s = _cfg("FIXED_AUTO_REPLY_SENDING_TIMEOUT_SECONDS", 300)
    max_attempts = _cfg("FIXED_AUTO_REPLY_MAX_SEND_ATTEMPTS", 3)
    failed = await db.execute(
        text(
            """
            UPDATE fixed_auto_reply_jobs
               SET status = 'failed',
                   failure_reason = 'send_attempts_exhausted',
                   updated_at = NOW()
             WHERE status = 'sending'
               AND send_attempts >= :max_attempts
               AND updated_at < NOW() - make_interval(secs => :timeout_s)
            """
        ),
        {"max_attempts": max_attempts, "timeout_s": timeout_s},
    )
    recovered = await db.execute(
        text(
            """
            UPDATE fixed_auto_reply_jobs
               SET status = 'pending',
                   send_attempts = send_attempts + 1,
                   failure_reason = NULL,
                   updated_at = NOW()
             WHERE status = 'sending'
               AND send_attempts < :max_attempts
               AND updated_at < NOW() - make_interval(secs => :timeout_s)
            """
        ),
        {"max_attempts": max_attempts, "timeout_s": timeout_s},
    )
    return {
        "recovered_to_pending": int(recovered.rowcount or 0),
        "marked_failed": int(failed.rowcount or 0),
    }


async def _count_connected_fixed_accounts(db) -> int:
    result = await db.execute(
        text(
            """
            SELECT COUNT(*)::int
              FROM telegram_accounts
             WHERE COALESCE(metadata->>'reply_mode', 'ai') = 'fixed'
               AND status = 'connected'
               AND is_active = TRUE
            """
        )
    )
    return max(1, int(result.scalar() or 1))


async def _enqueue_new_user_jobs(db) -> int:
    result = await db.execute(
        text(
            """
            WITH active_rules AS (
                SELECT
                    id AS rule_id,
                    GREATEST(0, delay_seconds) AS delay_seconds,
                    COALESCE(activated_at, created_at, NOW()) AS start_at
                FROM fixed_auto_reply_rules
                WHERE is_active = TRUE
            ),
            eligible AS (
                SELECT DISTINCT ON (r.rule_id, u.id)
                    r.rule_id,
                    CAST(md5(CAST(r.rule_id AS TEXT) || ':' || CAST(u.id AS TEXT)) AS UUID) AS job_id,
                    u.id AS user_id,
                    u.external_id AS external_user_id,
                    c.id AS conversation_id,
                    pc.account_id,
                    pc.chat_id,
                    pc.access_hash AS telegram_access_hash,
                    NOW() + make_interval(secs => r.delay_seconds) AS send_at
                FROM active_rules r
                JOIN users u
                    ON u.channel = 'telegram_real_user'
                   AND u.external_id LIKE 'tg_%'
                   AND u.created_at >= r.start_at
                LEFT JOIN conversations c
                    ON c.user_id = u.id
                   AND c.channel = 'telegram_real_user'
                LEFT JOIN LATERAL (
                    SELECT
                        account_id,
                        chat_id,
                        access_hash
                    FROM telegram_peer_cache pc
                    WHERE pc.user_id = u.id
                       OR pc.conversation_id = c.id
                       OR pc.chat_id = CASE
                            WHEN u.external_id ~ '^tg_[0-9]+$'
                            THEN SUBSTRING(u.external_id FROM 4)::BIGINT
                            ELSE NULL
                          END
                    ORDER BY
                        CASE WHEN pc.access_hash IS NULL THEN 1 ELSE 0 END,
                        pc.last_seen_at DESC NULLS LAST,
                        pc.updated_at DESC NULLS LAST
                    LIMIT 1
                ) pc ON TRUE
                JOIN telegram_accounts ta
                    ON ta.id = pc.account_id
                   AND COALESCE(ta.metadata->>'reply_mode', 'ai') = 'fixed'
                WHERE pc.chat_id IS NOT NULL
                ORDER BY r.rule_id, u.id, c.created_at ASC NULLS LAST
            ),
            reserved AS (
                INSERT INTO fixed_auto_reply_rule_recipients (
                    id,
                    rule_id,
                    user_id,
                    external_user_id,
                    first_job_id
                )
                SELECT
                    CAST(md5(CAST(rule_id AS TEXT) || ':' || external_user_id || '|recipient') AS UUID),
                    rule_id,
                    user_id,
                    external_user_id,
                    job_id
                FROM eligible
                ON CONFLICT (rule_id, external_user_id) DO NOTHING
                RETURNING rule_id, user_id, external_user_id, first_job_id
            ),
            inserted AS (
                INSERT INTO fixed_auto_reply_jobs (
                    rule_id,
                    id,
                    user_id,
                    conversation_id,
                    external_user_id,
                    account_id,
                    chat_id,
                    telegram_access_hash,
                    send_at
                )
                SELECT
                    e.rule_id,
                    e.job_id,
                    e.user_id,
                    e.conversation_id,
                    e.external_user_id,
                    e.account_id,
                    e.chat_id,
                    e.telegram_access_hash,
                    e.send_at
                FROM eligible e
                JOIN reserved r
                  ON r.rule_id = e.rule_id
                 AND r.user_id = e.user_id
                 AND r.external_user_id = e.external_user_id
                 AND r.first_job_id = e.job_id
                ON CONFLICT (rule_id, user_id) DO NOTHING
                RETURNING id
            )
            SELECT COUNT(*) AS count FROM inserted
            """
        )
    )
    return int(result.scalar() or 0)


async def enqueue_jobs_for_fixed_mode_inbound(
    db,
    *,
    user_id: str,
    conversation_id: str,
    external_user_id: str,
    account_id: str,
    chat_id: int,
    telegram_access_hash: int | None,
) -> int:
    """Queue active fixed-reply rules for one inbound message on a fixed-mode account."""
    await ensure_schema(db)
    result = await db.execute(
        text(
            """
            WITH active_rules AS (
                SELECT
                    id AS rule_id,
                    GREATEST(0, delay_seconds) AS delay_seconds,
                    COALESCE(activated_at, created_at, NOW()) AS start_at
                FROM fixed_auto_reply_rules
                WHERE is_active = TRUE
            ),
            fixed_user_seen AS (
                SELECT COALESCE(
                    (
                        SELECT MIN(created_at)
                          FROM fixed_auto_reply_jobs
                         WHERE external_user_id = :external_user_id
                    ),
                    NOW()
                ) AS first_seen_at
            ),
            eligible AS (
                SELECT
                    r.rule_id,
                    CAST(md5(CAST(r.rule_id AS TEXT) || ':' || CAST(:user_id AS TEXT)) AS UUID) AS job_id,
                    CAST(:user_id AS UUID) AS user_id,
                    CAST(:conversation_id AS UUID) AS conversation_id,
                    :external_user_id AS external_user_id,
                    CAST(:account_id AS UUID) AS account_id,
                    CAST(:chat_id AS BIGINT) AS chat_id,
                    CAST(:telegram_access_hash AS BIGINT) AS telegram_access_hash,
                    NOW() + make_interval(secs => r.delay_seconds) AS send_at
                FROM active_rules r
                JOIN telegram_accounts ta
                    ON ta.id = CAST(:account_id AS UUID)
                   AND COALESCE(ta.metadata->>'reply_mode', 'ai') = 'fixed'
                CROSS JOIN fixed_user_seen fus
                WHERE r.start_at <= fus.first_seen_at
            ),
            reserved AS (
                INSERT INTO fixed_auto_reply_rule_recipients (
                    id,
                    rule_id,
                    user_id,
                    external_user_id,
                    first_job_id
                )
                SELECT
                    CAST(md5(CAST(rule_id AS TEXT) || ':' || external_user_id || '|recipient') AS UUID),
                    rule_id,
                    user_id,
                    external_user_id,
                    job_id
                FROM eligible
                ON CONFLICT (rule_id, external_user_id) DO NOTHING
                RETURNING rule_id, user_id, external_user_id, first_job_id
            ),
            inserted AS (
                INSERT INTO fixed_auto_reply_jobs (
                    rule_id,
                    id,
                    user_id,
                    conversation_id,
                    external_user_id,
                    account_id,
                    chat_id,
                    telegram_access_hash,
                    send_at
                )
                SELECT
                    e.rule_id,
                    e.job_id,
                    e.user_id,
                    e.conversation_id,
                    e.external_user_id,
                    e.account_id,
                    e.chat_id,
                    e.telegram_access_hash,
                    e.send_at
                FROM eligible e
                JOIN reserved r
                  ON r.rule_id = e.rule_id
                 AND r.user_id = e.user_id
                 AND r.external_user_id = e.external_user_id
                 AND r.first_job_id = e.job_id
                ON CONFLICT (rule_id, user_id) DO NOTHING
                RETURNING id
            )
            SELECT COUNT(*) AS count FROM inserted
            """
        ),
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "external_user_id": external_user_id,
            "account_id": account_id,
            "chat_id": chat_id,
            "telegram_access_hash": telegram_access_hash,
        },
    )
    return int(result.scalar() or 0)


async def _claim_due_jobs_fair(
    db,
    *,
    trace_id: str,
    per_account_limit: int,
    total_limit: int,
) -> list[dict[str, Any]]:
    claim = await db.execute(
        text(
            """
            WITH due AS (
                SELECT
                    j.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY j.account_id
                        ORDER BY j.send_at ASC
                    ) AS rn
                  FROM fixed_auto_reply_jobs j
                  JOIN telegram_accounts ta ON ta.id=j.account_id AND ta.status='connected' AND ta.is_active
                  LEFT JOIN video_reinvite_account_state hs ON hs.account_id=j.account_id
                 WHERE j.status = 'pending'
                   AND j.send_at <= NOW()
                   AND j.account_id IS NOT NULL
                   AND COALESCE(hs.status,'active')='active'
                   AND COALESCE(hs.health_check_status,'healthy')='healthy'
                   AND (hs.resume_at IS NULL OR hs.resume_at<=NOW())
            ),
            picked AS (
                SELECT id
                  FROM due
                 WHERE rn <= :per_account_limit
                 ORDER BY id
                 LIMIT :total_limit
            )
            UPDATE fixed_auto_reply_jobs j
               SET status = 'sending',
                   trace_id = :trace_id,
                   updated_at = NOW()
              FROM picked
             WHERE j.id = picked.id
             RETURNING
                j.id,
                j.rule_id,
                j.user_id,
                j.conversation_id,
                j.external_user_id,
                j.account_id,
                j.chat_id,
                j.telegram_access_hash
            """
        ),
        {
            "trace_id": trace_id,
            "per_account_limit": per_account_limit,
            "total_limit": total_limit,
        },
    )
    jobs = [dict(row._mapping) for row in claim.fetchall()]
    await db.commit()
    return jobs


async def _send_due_jobs(*, trace_id: str) -> tuple[int, int]:
    per_account_limit = _cfg("FIXED_AUTO_REPLY_PER_ACCOUNT_BATCH", 10)
    max_total = _cfg("FIXED_AUTO_REPLY_MAX_TOTAL_BATCH", 200)
    max_parallel = _cfg("FIXED_AUTO_REPLY_MAX_PARALLEL_ACCOUNTS", 16)

    async with AsyncSessionLocal() as db:
        await ensure_schema(db)
        account_count = await _count_connected_fixed_accounts(db)
        total_limit = min(max_total, per_account_limit * account_count)
        jobs = await _claim_due_jobs_fair(
            db,
            trace_id=trace_id,
            per_account_limit=per_account_limit,
            total_limit=total_limit,
        )

    if not jobs:
        return 0, 0

    logger.bind(
        trace_id=trace_id,
        claimed=len(jobs),
        per_account_limit=per_account_limit,
        total_limit=total_limit,
        account_count=account_count,
    ).info("fixed_auto_reply.send.claimed")

    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        account_key = str(job.get("account_id") or "unknown")
        by_account[account_key].append(job)

    semaphore = asyncio.Semaphore(max_parallel)

    async def _send_account_jobs(account_id: str, account_jobs: list[dict[str, Any]]) -> tuple[int, int]:
        async with semaphore:
            sent_count = 0
            failed_count = 0
            for job in account_jobs:
                async with AsyncSessionLocal() as job_db:
                    ok, reason = await _send_one_job(job_db, job, trace_id=trace_id)
                if ok:
                    sent_count += 1
                else:
                    failed_count += 1
                    logger.bind(
                        trace_id=trace_id,
                        job_id=str(job.get("id")),
                        account_id=account_id,
                        reason=reason,
                    ).warning("fixed_auto_reply.job_failed")
            return sent_count, failed_count

    results = await asyncio.gather(
        *[_send_account_jobs(account_id, account_jobs) for account_id, account_jobs in by_account.items()]
    )
    sent = sum(item[0] for item in results)
    failed = sum(item[1] for item in results)
    return sent, failed


async def _asset_circuit_open(db, asset_id: Any) -> bool:
    threshold = _cfg("FIXED_AUTO_REPLY_ASSET_FAIL_CIRCUIT", 5)
    result = await db.execute(
        text(
            """
            WITH recent AS (
              SELECT status,error FROM fixed_auto_reply_deliveries
              WHERE asset_id=:asset_id AND error IS DISTINCT FROM 'asset_circuit_open'
                AND created_at>=NOW()-INTERVAL '30 minutes'
              ORDER BY created_at DESC LIMIT :threshold
            ) SELECT COUNT(*)::int FROM recent
              WHERE status='failed' AND error='asset_send_failed'
            """
        ),
        {"asset_id": asset_id, "threshold": threshold},
    )
    return int(result.scalar() or 0) >= threshold


async def _prepare_fixed_text_outbound(
    db,
    *,
    job: dict[str, Any],
    text_content: str,
    account_id: Any,
    trace_id: str,
) -> tuple[str, str, str]:
    """Wrap outbound links with /r/ tracking and build Telegram HTML when needed."""
    assistant_msg_id = str(uuid.uuid4())
    outbound_text = text_content
    if "http" in text_content:
        try:
            outbound_text = await wrap_text_links_with_tracking(
                db,
                text_value=text_content,
                base_url=str(settings.PUBLIC_BASE_URL).rstrip("/"),
                user_id=job.get("user_id"),
                conversation_id=job.get("conversation_id"),
                message_id=assistant_msg_id,
                platform="telegram_real_user",
                sender_account_id=str(account_id) if account_id else None,
                script_category="fixed_auto_reply",
                intent="fixed_auto_reply",
                metadata={
                    "source": "fixed_auto_reply",
                    "trace_id": trace_id,
                    "rule_id": str(job.get("rule_id") or ""),
                    "job_id": str(job.get("id") or ""),
                },
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.bind(
                error_type=type(exc).__name__,
                job_id=str(job.get("id") or ""),
            ).warning("fixed_auto_reply.link_attribution_failed")

    telegram_text = render_tracking_links_as_html_cta(outbound_text)
    return outbound_text, telegram_text, assistant_msg_id


async def _backfill_attribution_message_ids(
    db,
    *,
    message_id: str,
    outbound_text: str,
) -> None:
    """Attach persisted message rows to links created before the insert."""
    if "/r/" not in outbound_text:
        return
    tracking_ids: set[str] = set()
    for match in re.finditer(r"/r/([A-Za-z0-9]+)", outbound_text):
        tracking_ids.add(match.group(1))
    if not tracking_ids:
        return
    for tracking_id in tracking_ids:
        await db.execute(
            text(
                """
                UPDATE attribution_links
                   SET message_id = CAST(:message_id AS uuid)
                 WHERE tracking_id = :tracking_id
                   AND message_id IS NULL
                """
            ),
            {"message_id": message_id, "tracking_id": tracking_id},
        )
    await db.commit()


async def _send_one_job(db, job: dict[str, Any], *, trace_id: str) -> tuple[bool, str | None]:
    rule_row = await db.execute(
        text(
            """
            SELECT id, text_content
              FROM fixed_auto_reply_rules
             WHERE id = :rule_id
               AND is_active = TRUE
            """
        ),
        {"rule_id": job["rule_id"]},
    )
    rule = rule_row.mappings().first()
    if not rule:
        await _mark_job(db, job["id"], "skipped", "rule_disabled")
        return False, "rule_disabled"

    if not await _rule_allowed_for_job(db, job):
        await _mark_job(db, job["id"], "skipped", "rule_created_after_fixed_user_seen")
        return False, "rule_created_after_fixed_user_seen"

    assets_row = await db.execute(
        text(
            """
            SELECT
                id,
                asset_type,
                asset_url,
                storage_path,
                caption,
                sort_order
              FROM fixed_auto_reply_assets
             WHERE rule_id = :rule_id
             ORDER BY sort_order ASC, created_at ASC
            """
        ),
        {"rule_id": job["rule_id"]},
    )
    assets = [dict(row._mapping) for row in assets_row.fetchall()]

    account_id = job.get("account_id")
    chat_id = job.get("chat_id")
    if not chat_id:
        await _mark_job(db, job["id"], "failed", "missing_chat_id")
        return False, "missing_chat_id"

    allowed, gate_reason, resume_at = await check_outbound_account(db, str(account_id) if account_id else None)
    if not allowed:
        delay = max(300, int((resume_at.timestamp() - datetime.now(resume_at.tzinfo).timestamp()))) if resume_at else 3600
        await _defer_job(db, job["id"], gate_reason, delay_seconds=delay)
        return False, f"deferred:{gate_reason}"

    text_timeout = _cfg("FIXED_AUTO_REPLY_TEXT_SEND_TIMEOUT_SECONDS", 15)
    media_timeout = _cfg("FIXED_AUTO_REPLY_MEDIA_SEND_TIMEOUT_SECONDS", 60)

    try:
        client = await _ensure_job_client(account_id)
        if client is None:
            reason = "telegram_account_missing"
            status = await _mark_job_retry(db, job["id"], reason, delay_seconds=60)
            return False, reason if status == "failed" else f"retry:{reason}"

        peer = await _resolve_peer_for_job(db, client, job)

        text_content = str(rule.get("text_content") or "").strip()
        if text_content:
            outbound_text, telegram_text, assistant_msg_id = await _prepare_fixed_text_outbound(
                db,
                job=job,
                text_content=text_content,
                account_id=account_id,
                trace_id=trace_id,
            )
            await _send_fixed_text_message(
                client,
                peer,
                outbound_text=outbound_text,
                telegram_text=telegram_text,
                timeout_s=text_timeout,
            )
            await _record_delivery(db, job, "text", None, "sent", None)
            await _persist_assistant_message(
                db,
                job,
                outbound_text,
                message_id=assistant_msg_id,
            )
            await _backfill_attribution_message_ids(
                db,
                message_id=assistant_msg_id,
                outbound_text=outbound_text,
            )

        for asset in assets:
            if await _asset_circuit_open(db, asset["id"]):
                await _record_delivery(
                    db,
                    job,
                    asset["asset_type"],
                    asset["id"],
                    "failed",
                    "asset_circuit_open",
                )
                await _mark_job(db, job["id"], "failed", "asset_circuit_open")
                return False, "asset_circuit_open"

            asset_type = str(asset.get("asset_type") or "").lower()
            timeout_s = media_timeout if asset_type in {"video", "voice", "audio"} else min(media_timeout, 30)
            try:
                sent_asset = await asyncio.wait_for(
                    send_mtproto_asset(client, peer, asset, trace_id=trace_id),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                sent_asset = None
            if sent_asset is None:
                await _record_delivery(db, job, asset["asset_type"], asset["id"], "failed", "asset_send_failed")
                await _mark_job(db, job["id"], "failed", "asset_send_failed")
                return False, "asset_send_failed"
            await _record_delivery(db, job, asset["asset_type"], asset["id"], "sent", None)

        if not text_content and not assets:
            await _mark_job(db, job["id"], "skipped", "empty_rule")
            return False, "empty_rule"

        await _mark_job(db, job["id"], "sent", None)
        return True, None
    except asyncio.TimeoutError:
        reason = "send_timeout"
        status = await _mark_job_retry(db, job["id"], reason, delay_seconds=45)
        return False, reason if status == "failed" else f"retry:{reason}"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:180]}"
        if "peerflood" in reason.lower() and account_id:
            await pause_outbound_account(db, str(account_id), reason=reason, hours=24)
            await _defer_job(db, job["id"], reason, delay_seconds=86400)
            await db.commit()
            return False, "deferred:peer_flood"
        if _is_retryable_fixed_reply_failure(reason):
            delay = 120 if "peerflood" in reason.lower() else 30
            status = await _mark_job_retry(db, job["id"], reason, delay_seconds=delay)
            return False, reason if status == "failed" else f"retry:{reason}"
        await _mark_job(db, job["id"], "failed", reason)
        return False, reason


async def _lookup_peer_access_hash_from_cache(db, job: dict[str, Any]) -> int | None:
    row = (
        await db.execute(
            text(
                """
                SELECT access_hash
                  FROM telegram_peer_cache
                 WHERE account_id = CAST(:account_id AS uuid)
                   AND chat_id = :chat_id
                   AND access_hash IS NOT NULL
                 ORDER BY last_seen_at DESC NULLS LAST, updated_at DESC NULLS LAST
                 LIMIT 1
                """
            ),
            {
                "account_id": str(job.get("account_id") or ""),
                "chat_id": int(job.get("chat_id") or 0),
            },
        )
    ).first()
    if row is None:
        return None
    data = row._mapping if hasattr(row, "_mapping") else row
    value = data.get("access_hash")
    return int(value) if value is not None else None


def _is_retryable_fixed_reply_failure(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = reason.lower()
    retry_markers = (
        "peerflooderror",
        "floodwaiterror",
        "timedouterror",
        "send_timeout",
        "telegram_account_missing",
        "could not resolve telegram peer",
        "timeout",
    )
    return any(marker in normalized for marker in retry_markers)


async def _mark_job_retry(
    db,
    job_id: Any,
    failure_reason: str,
    *,
    delay_seconds: int = 30,
) -> str:
    max_attempts = _cfg("FIXED_AUTO_REPLY_MAX_SEND_ATTEMPTS", 3)
    row = (
        await db.execute(
            text(
                """
                UPDATE fixed_auto_reply_jobs
                   SET send_attempts = send_attempts + 1,
                       failure_reason = :failure_reason,
                       status = CASE
                           WHEN send_attempts + 1 >= :max_attempts THEN 'failed'
                           ELSE 'pending'
                       END,
                       send_at = CASE
                           WHEN send_attempts + 1 >= :max_attempts THEN send_at
                           ELSE NOW() + make_interval(secs => :delay_seconds)
                       END,
                       updated_at = NOW()
                 WHERE id = :job_id
                 RETURNING status
                """
            ),
            {
                "job_id": job_id,
                "failure_reason": failure_reason[:500],
                "max_attempts": max_attempts,
                "delay_seconds": max(5, int(delay_seconds)),
            },
        )
    ).first()
    await db.commit()
    if row is None:
        return "failed"
    data = row._mapping if hasattr(row, "_mapping") else row
    return str(data.get("status") or "failed")


async def _defer_job(db, job_id: Any, reason: str, *, delay_seconds: int) -> None:
    await db.execute(text("""
      UPDATE fixed_auto_reply_jobs SET status='pending',failure_reason=:reason,
        send_at=NOW()+make_interval(secs=>:delay),updated_at=NOW()
      WHERE id=:job_id AND status='sending'
    """), {"job_id": job_id, "reason": reason[:500], "delay": max(30, int(delay_seconds))})
    await db.commit()


async def _resolve_peer_for_job(db, client: Any, job: dict[str, Any]) -> Any:
    chat_id = int(job["chat_id"])
    access_hash = job.get("telegram_access_hash")
    if access_hash is not None:
        try:
            return await resolve_telethon_peer(
                client,
                chat_id,
                access_hash=int(access_hash),
            )
        except ValueError:
            pass

    refreshed = await _lookup_peer_access_hash_from_cache(db, job)
    if refreshed is not None:
        job["telegram_access_hash"] = refreshed
        return await resolve_telethon_peer(client, chat_id, access_hash=refreshed)

    return await resolve_telethon_peer(
        client,
        chat_id,
        access_hash=int(access_hash) if access_hash is not None else None,
    )


async def _send_fixed_text_message(
    client: Any,
    peer: Any,
    *,
    outbound_text: str,
    telegram_text: str,
    timeout_s: int,
) -> None:
    send_kwargs: dict[str, Any] = {}
    if telegram_text != outbound_text:
        send_kwargs["parse_mode"] = "html"
    try:
        await asyncio.wait_for(
            client.send_message(peer, telegram_text, **send_kwargs),
            timeout=timeout_s,
        )
    except Exception as exc:
        if send_kwargs.get("parse_mode") != "html":
            raise
        exc_name = type(exc).__name__.lower()
        if "parse" not in exc_name and "entity" not in str(exc).lower():
            raise
        await asyncio.wait_for(
            client.send_message(peer, outbound_text),
            timeout=timeout_s,
        )


async def _ensure_job_client(account_id: Any) -> Any | None:
    client = None
    if account_id:
        client = await telegram_account_manager.get_client(uuid.UUID(str(account_id)))
        if client is None:
            try:
                connected = await telegram_account_manager.connect_account(
                    uuid.UUID(str(account_id))
                )
            except Exception:
                connected = False
            if connected:
                client = await telegram_account_manager.get_client(uuid.UUID(str(account_id)))
    if client is None:
        client = await telegram_account_manager.get_any_connected_client()
    return client


async def _rule_allowed_for_job(db, job: dict[str, Any]) -> bool:
    result = await db.execute(
        text(
            """
            WITH this_job AS (
                SELECT id, rule_id, external_user_id, created_at
                  FROM fixed_auto_reply_jobs
                 WHERE id = :job_id
            ),
            first_fixed_seen AS (
                SELECT COALESCE(
                    (
                        SELECT MIN(j2.created_at)
                          FROM fixed_auto_reply_jobs j2
                          JOIN this_job tj
                            ON tj.external_user_id = j2.external_user_id
                         WHERE j2.created_at < tj.created_at
                    ),
                    (SELECT created_at FROM this_job)
                ) AS first_seen_at
            )
            SELECT COALESCE(r.activated_at, r.created_at, NOW()) <= ffs.first_seen_at AS allowed
              FROM fixed_auto_reply_rules r
              JOIN this_job tj
                ON tj.rule_id = r.id
             CROSS JOIN first_fixed_seen ffs
            """
        ),
        {"job_id": job["id"]},
    )
    allowed = result.scalar()
    return bool(allowed)


async def _record_delivery(
    db,
    job: dict[str, Any],
    item_type: str,
    asset_id: Any | None,
    status: str,
    error: str | None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO fixed_auto_reply_deliveries (
                id, job_id, rule_id, item_type, asset_id, status, error, sent_at
            )
            VALUES (
                :id, :job_id, :rule_id, :item_type, :asset_id, :status, :error,
                CASE WHEN :status = 'sent' THEN NOW() ELSE NULL END
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "job_id": job["id"],
            "rule_id": job["rule_id"],
            "item_type": item_type,
            "asset_id": asset_id,
            "status": status,
            "error": error,
        },
    )
    await db.commit()


async def _mark_job(db, job_id: Any, status: str, failure_reason: str | None) -> None:
    await db.execute(
        text(
            """
            UPDATE fixed_auto_reply_jobs
               SET status = :status,
                   failure_reason = :failure_reason,
                   sent_at = CASE WHEN :status = 'sent' THEN NOW() ELSE sent_at END,
                   updated_at = NOW()
             WHERE id = :job_id
            """
        ),
        {"job_id": job_id, "status": status, "failure_reason": failure_reason},
    )
    await db.commit()


async def _persist_assistant_message(
    db,
    job: dict[str, Any],
    content: str,
    *,
    message_id: str | None = None,
) -> None:
    conversation_id = job.get("conversation_id")
    if not conversation_id:
        return
    await db.execute(
        text(
            """
            INSERT INTO messages (
                id,
                conversation_id,
                sender_type,
                sender_id,
                content,
                content_type,
                model_name,
                created_at
            )
            VALUES (
                :id,
                :conversation_id,
                'assistant',
                :sender_id,
                :content,
                'text',
                'fixed_auto_reply',
                NOW()
            )
            """
        ),
        {
            "id": message_id or str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "sender_id": str(job.get("account_id") or "fixed_auto_reply"),
            "content": content,
        },
    )
    await db.execute(
        text("UPDATE conversations SET last_message_at = NOW(), updated_at = NOW() WHERE id = :id"),
        {"id": conversation_id},
    )
    await db.commit()
