"""Isolated migration worker for users whose receiving TG account was banned."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.process_role import is_dedicated_telegram_runtime
from services.telegram_account_manager import telegram_account_manager
from services.telegram_peer_cache import upsert_telegram_peer_cache

_scheduler: AsyncIOScheduler | None = None
_tick_lock = asyncio.Lock()
JOB_ID = "telegram-user-migration-worker"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
RUNTIME_STARTED_AT = datetime.now(timezone.utc)
RUNTIME_GRACE_SECONDS = 30 * 60
TIER_LIMITS = {
    1: {"hourly": 1, "initial_daily": 3, "daily": 10, "min_minutes": 45, "max_minutes": 75},
    2: {"hourly": 2, "initial_daily": 4, "daily": 12, "min_minutes": 25, "max_minutes": 45},
    3: {"hourly": 2, "initial_daily": 5, "daily": 14, "min_minutes": 20, "max_minutes": 40},
    4: {"hourly": 3, "initial_daily": 5, "daily": 15, "min_minutes": 15, "max_minutes": 30},
}


def _execution_gate_reason() -> str | None:
    if (datetime.now(timezone.utc) - RUNTIME_STARTED_AT).total_seconds() < RUNTIME_GRACE_SECONDS:
        return "runtime_grace_period"
    now = datetime.now(BEIJING_TZ)
    current = now.time().replace(tzinfo=None)
    if current < time(10, 0) or current >= time(22, 0):
        return "outside_beijing_window"
    if time(17, 30) <= current < time(18, 30):
        return "health_check_pause_window"
    return None


def _error_status(exc: Exception, attempts: int) -> tuple[str, str, int]:
    name = type(exc).__name__
    message = str(exc)[:500]
    lowered = f"{name} {message}".lower()
    if any(token in lowered for token in ("privacy", "blocked", "userisblocked", "inputuserdeactivated")):
        return "unreachable", name, 0
    if any(token in lowered for token in ("flood", "peerflood", "restricted", "spam")):
        return "restricted", name, 3600
    if attempts < 3:
        return "retry_wait", name, min(3600, 60 * (2 ** max(0, attempts - 1)))
    return "failed", name, 0


async def mark_inbound_migration_reply(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
    user_id: str,
) -> bool:
    """Confirm migration when the user replies to the designated new account."""
    row = (
        await db.execute(
            text(
                """
                UPDATE telegram_user_migration_tasks
                SET status = 'success', replied_at = NOW(), updated_at = NOW(),
                    video_sequence_reset_at = COALESCE(video_sequence_reset_at, sent_at, NOW()),
                    metadata = metadata || jsonb_build_object('profile_linked', true)
                WHERE id = (
                    SELECT id FROM telegram_user_migration_tasks
                    WHERE target_account_id = CAST(:account_id AS uuid)
                      AND telegram_chat_id = :chat_id
                      AND user_id = CAST(:user_id AS uuid)
                      AND status IN ('sent','resolved','sending','retry_wait')
                    ORDER BY created_at DESC LIMIT 1
                )
                RETURNING id
                """
            ),
            {"account_id": account_id, "chat_id": int(chat_id), "user_id": user_id},
        )
    ).first()
    if row:
        logger.bind(account_id=account_id, chat_id=chat_id, user_id=user_id).info(
            "telegram_user_migration.inbound_linked"
        )
    return bool(row)


async def migration_video_cutover(
    db: AsyncSession,
    *,
    account_id: str,
    chat_id: int,
) -> datetime | None:
    """Return cutover only for an explicitly migrated user on the new account."""
    row = (
        await db.execute(
            text(
                """
                SELECT COALESCE(video_sequence_reset_at, sent_at)
                FROM telegram_user_migration_tasks
                WHERE target_account_id = CAST(:account_id AS uuid)
                  AND telegram_chat_id = :chat_id
                  AND status = 'success'
                  AND video_sequence_reset_at IS NOT NULL
                ORDER BY video_sequence_reset_at DESC LIMIT 1
                """
            ),
            {"account_id": account_id, "chat_id": int(chat_id)},
        )
    ).first()
    return row[0] if row else None


async def _claim_tasks(db: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                WITH eligible AS (
                    SELECT id FROM (
                      SELECT t.id, t.campaign_id, t.next_attempt_at, t.created_at,
                             ROW_NUMBER() OVER (
                               PARTITION BY t.campaign_id
                               ORDER BY t.next_attempt_at, t.created_at
                             ) AS rn
                      FROM telegram_user_migration_tasks t
                      JOIN telegram_user_migration_campaigns c ON c.id=t.campaign_id
                      JOIN telegram_accounts source_account
                        ON source_account.id=t.source_account_id
                      LEFT JOIN video_reinvite_account_state source_state
                        ON source_state.account_id=t.source_account_id
                      WHERE c.status='running'
                        AND t.status IN ('pending','retry_wait')
                        AND t.next_attempt_at <= NOW()
                        AND (
                          (source_account.status='banned'
                           AND source_account.updated_at <
                               date_trunc('day', NOW() AT TIME ZONE 'Asia/Shanghai')
                               AT TIME ZONE 'Asia/Shanghai')
                          OR
                          (source_state.health_check_status='banned'
                           AND source_state.paused_at <
                               date_trunc('day', NOW() AT TIME ZONE 'Asia/Shanghai')
                               AT TIME ZONE 'Asia/Shanghai')
                        )
                    ) ranked
                    WHERE rn <= :limit
                    ORDER BY next_attempt_at, created_at
                    LIMIT :limit
                ), locked AS (
                    SELECT t.id
                    FROM telegram_user_migration_tasks t
                    JOIN eligible e ON e.id=t.id
                    FOR UPDATE OF t SKIP LOCKED
                )
                UPDATE telegram_user_migration_tasks t
                SET status = 'resolving', attempt_count = attempt_count + 1, updated_at = NOW()
                FROM locked e
                WHERE t.id = e.id
                RETURNING t.id::text, t.campaign_id::text, t.user_id::text,
                          t.conversation_id::text, t.telegram_chat_id,
                          t.source_account_id::text, t.target_account_id::text,
                          t.source_access_hash, t.attempt_count
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _select_safe_target(task: dict[str, Any]) -> dict[str, Any] | None:
    """Select one healthy target under tier, hourly, daily and interval limits."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    WITH candidate AS (
                      SELECT a.id::text AS account_id, s.tier,
                             COALESCE(hourly.sent,0) AS hourly_sent,
                             COALESCE(daily.sent,0) AS daily_sent,
                             recent.last_sent_at,
                             first_use.first_sent_at,
                             COALESCE(NULLIF(a.metadata->>'app_download_platform',''),'default') AS platform_key,
                             account_user.language AS account_language,
                             route.platform_key AS country_platform,
                             source.metadata->>'app_download_platform' AS source_platform,
                             migration_user.language AS migration_user_language
                      FROM telegram_accounts a
                      JOIN video_reinvite_account_state s ON s.account_id=a.id
                      JOIN telegram_accounts source ON source.id=CAST(:source_id AS uuid)
                      JOIN users migration_user ON migration_user.id=CAST(:user_id AS uuid)
                      LEFT JOIN user_profiles profile ON profile.user_id=migration_user.id
                      LEFT JOIN app_download_country_routes route ON route.country_code=profile.country_code
                      LEFT JOIN users account_user
                        ON account_user.channel='telegram_real_user'
                       AND account_user.external_id=('tg_' || a.user_id::text)
                      LEFT JOIN LATERAL (
                        SELECT COUNT(*)::int sent
                        FROM telegram_user_migration_tasks x
                        WHERE x.target_account_id=a.id
                          AND x.sent_at>=NOW()-INTERVAL '1 hour'
                      ) hourly ON TRUE
                      LEFT JOIN LATERAL (
                        SELECT COUNT(*)::int sent
                        FROM telegram_user_migration_tasks x
                        WHERE x.target_account_id=a.id
                          AND x.sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                               AT TIME ZONE 'Asia/Shanghai'
                      ) daily ON TRUE
                      LEFT JOIN LATERAL (
                        SELECT MAX(x.sent_at) last_sent_at
                        FROM telegram_user_migration_tasks x
                        WHERE x.target_account_id=a.id AND x.sent_at IS NOT NULL
                      ) recent ON TRUE
                      LEFT JOIN LATERAL (
                        SELECT MIN(x.sent_at) first_sent_at
                        FROM telegram_user_migration_tasks x
                        WHERE x.target_account_id=a.id AND x.sent_at IS NOT NULL
                      ) first_use ON TRUE
                      WHERE a.id<>CAST(:source_id AS uuid)
                        AND a.status='connected' AND a.is_active
                        AND s.status='active'
                        AND s.health_check_status='healthy'
                        AND s.last_health_check_at>=
                            date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                            AT TIME ZONE 'Asia/Shanghai'
                        AND (s.last_peer_flood_at IS NULL OR s.last_peer_flood_at<
                            date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                            AT TIME ZONE 'Asia/Shanghai')
                        AND (s.last_restricted_at IS NULL OR s.last_restricted_at<
                            date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                            AT TIME ZONE 'Asia/Shanghai')
                        AND s.tier BETWEEN 1 AND 4
                        AND EXISTS (
                          SELECT 1
                          FROM telegram_peer_cache target_peer
                          WHERE target_peer.account_id=a.id
                            AND target_peer.user_id=migration_user.id
                            AND target_peer.chat_id=:chat_id
                            AND target_peer.access_hash IS NOT NULL
                        )
                    )
                    SELECT account_id,tier FROM candidate
                    WHERE hourly_sent < CASE tier WHEN 1 THEN 1 WHEN 2 THEN 2 WHEN 3 THEN 2 ELSE 3 END
                      AND daily_sent < CASE
                        WHEN first_sent_at IS NULL OR first_sent_at>NOW()-INTERVAL '3 days'
                          THEN CASE tier WHEN 1 THEN 3 WHEN 2 THEN 4 ELSE 5 END
                        ELSE CASE tier WHEN 1 THEN 10 WHEN 2 THEN 12 WHEN 3 THEN 14 ELSE 15 END
                      END
                      AND (
                        last_sent_at IS NULL OR last_sent_at <= NOW()-make_interval(mins =>
                          CASE tier
                            WHEN 1 THEN 45+FLOOR(random()*31)::int
                            WHEN 2 THEN 25+FLOOR(random()*21)::int
                            WHEN 3 THEN 20+FLOOR(random()*21)::int
                            ELSE 15+FLOOR(random()*16)::int
                          END)
                      )
                    ORDER BY
                      (country_platform IS NOT NULL AND platform_key=country_platform) DESC,
                      (source_platform IS NOT NULL AND platform_key=source_platform) DESC,
                      (account_language IS NOT NULL AND migration_user_language IS NOT NULL
                       AND LOWER(account_language)=LOWER(migration_user_language)) DESC,
                      daily_sent ASC, hourly_sent ASC, random()
                    LIMIT 1
                    """
                ),
                {
                    "source_id": task["source_account_id"],
                    "user_id": task["user_id"],
                    "chat_id": int(task["telegram_chat_id"]),
                },
            )
        ).mappings().first()
    return dict(row) if row else None


async def _recover_stale_tasks(db: AsyncSession) -> int:
    """Release claims abandoned by a stopped worker without consuming a retry."""
    result = await db.execute(
        text(
            """
            UPDATE telegram_user_migration_tasks
            SET status = 'pending',
                next_attempt_at = NOW(),
                failure_code = 'recovered_stale_claim',
                failure_reason = 'recovered:stale_claim',
                updated_at = NOW()
            WHERE status IN ('resolving', 'resolved', 'sending')
              AND updated_at < NOW() - INTERVAL '10 minutes'
            """
        )
    )
    return int(result.rowcount or 0)


async def _campaign_is_running(db: AsyncSession, campaign_id: str) -> bool:
    value = (
        await db.execute(
            text(
                "SELECT 1 FROM telegram_user_migration_campaigns "
                "WHERE id=CAST(:id AS uuid) AND status='running'"
            ),
            {"id": campaign_id},
        )
    ).first()
    return bool(value)


async def _target_access_hash(*, account_id: str, chat_id: int) -> int | None:
    """Use only peer credentials learned by the target account itself."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT access_hash
                    FROM telegram_peer_cache
                    WHERE account_id=CAST(:account_id AS uuid)
                      AND chat_id=:chat_id
                      AND access_hash IS NOT NULL
                    ORDER BY last_seen_at DESC
                    LIMIT 1
                    """
                ),
                {"account_id": account_id, "chat_id": int(chat_id)},
            )
        ).first()
    return int(row[0]) if row and row[0] is not None else None


async def _process_task(task: dict[str, Any]) -> None:
    task_id = task["id"]
    log = logger.bind(component="telegram_user_migration", task_id=task_id)
    try:
        async with AsyncSessionLocal() as db:
            campaign = (
                await db.execute(
                    text(
                        "SELECT intro_message, filters->>'migration_image_path' AS image_path "
                        "FROM telegram_user_migration_campaigns "
                        "WHERE id=CAST(:id AS uuid) AND status='running'"
                    ),
                    {"id": task["campaign_id"]},
                )
            ).first()
            if not campaign:
                await db.execute(
                    text(
                        "UPDATE telegram_user_migration_tasks SET status='pending', "
                        "attempt_count=GREATEST(attempt_count-1,0), updated_at=NOW() "
                        "WHERE id=CAST(:id AS uuid) AND status='resolving'"
                    ),
                    {"id": task_id},
                )
                await db.commit()
                return
            intro_message = str(campaign[0])
            image_path = str(campaign[1] or "").strip()

        safe_target = await _select_safe_target(task)
        if safe_target is None:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        """
                        UPDATE telegram_user_migration_tasks
                        SET status='pending', attempt_count=GREATEST(attempt_count-1,0),
                            next_attempt_at=NOW()+INTERVAL '5 minutes',
                            failure_code='no_safe_target_available',
                            failure_reason='等待符合健康、时间和分级额度规则的接管账号',
                            updated_at=NOW()
                        WHERE id=CAST(:id AS uuid)
                        """
                    ),
                    {"id": task_id},
                )
                await db.commit()
            log.info("telegram_user_migration.wait_safe_target")
            return
        task["target_account_id"] = safe_target["account_id"]
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE telegram_user_migration_tasks
                    SET target_account_id=CAST(:target_id AS uuid),
                        metadata=metadata || jsonb_build_object(
                          'auto_assigned',true,'assigned_tier',CAST(:tier AS text),
                          'assigned_at',NOW()::text
                        ), updated_at=NOW()
                    WHERE id=CAST(:id AS uuid)
                    """
                ),
                {"id": task_id, "target_id": safe_target["account_id"], "tier": safe_target["tier"]},
            )
            await db.commit()

        account_id = UUID(task["target_account_id"])
        from services.runtime_ownership import legacy_worker_should_handle_account

        if (
            not is_dedicated_telegram_runtime()
            and not await legacy_worker_should_handle_account(str(account_id))
        ):
            logger.bind(account_id=str(account_id)).info(
                "telegram_user_migration.skip_runtime_owned"
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        """
                        UPDATE telegram_user_migration_tasks
                           SET status = 'pending',
                               attempt_count = GREATEST(attempt_count - 1, 0),
                               next_attempt_at = NOW() + INTERVAL '30 seconds',
                               updated_at = NOW()
                         WHERE id = CAST(:id AS uuid)
                           AND status = 'resolving'
                        """
                    ),
                    {"id": task_id},
                )
                await db.commit()
            return
        client = await telegram_account_manager.get_client(account_id)
        if client is None:
            connected = await telegram_account_manager.connect_account(account_id)
            client = await telegram_account_manager.get_client(account_id) if connected else None
        if client is None:
            raise RuntimeError("target account is not connected")

        chat_id = int(task["telegram_chat_id"])
        peer: Any = chat_id
        access_hash = await _target_access_hash(
            account_id=str(account_id), chat_id=chat_id
        )
        if access_hash:
            try:
                from telethon.tl.types import InputPeerUser

                peer = InputPeerUser(user_id=chat_id, access_hash=access_hash)
                peer = await client.get_input_entity(peer)
            except Exception:
                peer = await client.get_entity(chat_id)
        else:
            peer = await client.get_input_entity(chat_id)

        resolved_access_hash = getattr(peer, "access_hash", None)
        try:
            resolved_entity = await client.get_entity(peer)
            resolved_access_hash = getattr(resolved_entity, "access_hash", resolved_access_hash)
            async with AsyncSessionLocal() as db:
                await upsert_telegram_peer_cache(
                    db,
                    user_id=task["user_id"],
                    conversation_id=task["conversation_id"],
                    account_id=str(account_id),
                    chat_id=chat_id,
                    access_hash=resolved_access_hash,
                    source="telegram_user_migration_target_verified",
                    peer_metadata={
                        "username": getattr(resolved_entity, "username", None),
                        "first_name": getattr(resolved_entity, "first_name", None),
                        "last_name": getattr(resolved_entity, "last_name", None),
                        "target_account_verified": True,
                        "target_verified_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await db.commit()
        except Exception as exc:
            log.bind(error_type=type(exc).__name__).warning(
                "telegram_user_migration.target_peer_cache_failed"
            )

        async with AsyncSessionLocal() as db:
            if not await _campaign_is_running(db, task["campaign_id"]):
                await db.execute(
                    text(
                        "UPDATE telegram_user_migration_tasks SET status='pending', "
                        "attempt_count=GREATEST(attempt_count-1,0), updated_at=NOW() "
                        "WHERE id=CAST(:id AS uuid) AND status='resolving'"
                    ),
                    {"id": task_id},
                )
                await db.commit()
                return
            await db.execute(
                text("UPDATE telegram_user_migration_tasks SET status='sending', resolved_at=NOW(), updated_at=NOW() WHERE id=CAST(:id AS uuid)"),
                {"id": task_id},
            )
            await db.commit()

        if image_path:
            sent = await client.send_file(peer, image_path, caption=intro_message)
        else:
            sent = await client.send_message(peer, intro_message)
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE telegram_user_migration_tasks
                    SET status='sent', sent_at=NOW(), video_sequence_reset_at=NULL,
                        failure_code=NULL, failure_reason=NULL, updated_at=NOW(),
                        metadata=metadata || jsonb_build_object(
                            'telegram_message_id', CAST(:message_id AS text)
                        )
                    WHERE id=CAST(:id AS uuid)
                    """
                ),
                {"id": task_id, "message_id": str(getattr(sent, "id", ""))},
            )
            await db.commit()
        log.bind(has_image=bool(image_path)).info("telegram_user_migration.sent")
    except Exception as exc:
        status, code, retry_seconds = _error_status(exc, int(task.get("attempt_count") or 1))
        target_restricted = status == "restricted"
        if target_restricted:
            status = "retry_wait"
            retry_seconds = 300
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE telegram_user_migration_tasks
                    SET status=:status, failure_code=:code, failure_reason=:reason,
                        next_attempt_at=CASE WHEN :retry_seconds > 0
                          THEN NOW() + make_interval(secs => :retry_seconds) ELSE next_attempt_at END,
                        updated_at=NOW()
                    WHERE id=CAST(:id AS uuid)
                    """
                ),
                {"id": task_id, "status": status, "code": code, "reason": str(exc)[:500], "retry_seconds": retry_seconds},
            )
            if target_restricted and task.get("target_account_id"):
                await db.execute(
                    text(
                        """
                        UPDATE video_reinvite_account_state
                        SET status='paused', paused_at=NOW(), resume_at=NULL,
                            pause_reason='telegram_migration_send_restricted',
                            last_restricted_at=NOW(), updated_at=NOW()
                        WHERE account_id=CAST(:account_id AS uuid)
                        """
                    ),
                    {"account_id": task["target_account_id"]},
                )
                await db.execute(
                    text(
                        """
                        UPDATE telegram_user_migration_tasks
                        SET next_attempt_at=GREATEST(next_attempt_at,NOW()+INTERVAL '5 minutes'),
                            metadata=metadata || jsonb_build_object(
                              'reassign_reason','target_restricted',
                              'restricted_target_account_id',:account_id
                            ), updated_at=NOW()
                        WHERE target_account_id=CAST(:account_id AS uuid)
                          AND status IN ('pending','retry_wait')
                        """
                    ),
                    {"account_id": task["target_account_id"]},
                )
            await db.commit()
        log.bind(error_type=type(exc).__name__, migration_status=status).warning(
            "telegram_user_migration.failed"
        )


async def run_one_tick() -> dict[str, int]:
    gate_reason = _execution_gate_reason()
    if gate_reason:
        return {"claimed": 0, "gated": 1}
    if _tick_lock.locked():
        return {"claimed": 0}
    async with _tick_lock:
        async with AsyncSessionLocal() as db:
            recovered = await _recover_stale_tasks(db)
            if recovered:
                logger.bind(recovered=recovered).warning(
                    "telegram_user_migration.stale_tasks_recovered"
                )
            tasks = await _claim_tasks(db)
            await db.commit()
        for task in tasks:
            await _process_task(task)
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE telegram_user_migration_campaigns c
                    SET status='completed', completed_at=NOW(), updated_at=NOW()
                    WHERE c.status='running'
                      AND NOT EXISTS (
                        SELECT 1 FROM telegram_user_migration_tasks t
                        WHERE t.campaign_id=c.id
                          AND t.status IN ('pending','resolving','resolved','sending','retry_wait')
                      )
                    """
                )
            )
            await db.commit()
        return {"claimed": len(tasks)}


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_one_tick, "interval", seconds=5, id=JOB_ID, max_instances=1, coalesce=True)
    scheduler.start()
    _scheduler = scheduler
    logger.info("telegram_user_migration.scheduler.started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
