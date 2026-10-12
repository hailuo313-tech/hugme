"""Conservative T+1/T+3/T+7 video reinvitation worker."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import text

from core.database import AsyncSessionLocal
from services.mtproto.peer_resolve import resolve_telethon_peer
from services.telegram_account_manager import telegram_account_manager
from services.telegram_account_health import run_health_check

JOB_ID = "video-reinvite-worker"
_scheduler: AsyncIOScheduler | None = None
_tick_lock = asyncio.Lock()


async def evaluate_account_tiers() -> dict[str, int]:
    """Daily Beijing-time tier/health evaluation and gradual ramp-up."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("""INSERT INTO video_reinvite_account_state
          (account_id,platform_connected_at,tier,tier_changed_at,effective_daily_limit,effective_min_interval_seconds)
          SELECT a.id,COALESCE(NULLIF(a.metadata->>'platform_connected_at','')::timestamptz,
                 a.created_at AT TIME ZONE 'UTC',a.last_connected_at AT TIME ZONE 'UTC',NOW()),
                 1,NOW(),8,180
          FROM telegram_accounts a WHERE a.status='connected' AND a.is_active
          ON CONFLICT(account_id) DO NOTHING"""))
        await db.execute(text("""WITH stats AS (
          SELECT s.account_id,COUNT(a.id) attempts,
                 COUNT(a.id) FILTER(WHERE a.status='sent') successes
          FROM video_reinvite_account_state s LEFT JOIN video_reinvite_attempts a
            ON a.account_id=s.account_id AND a.created_at>=NOW()-INTERVAL '7 days'
          GROUP BY s.account_id
        ) UPDATE video_reinvite_account_state s SET
          seven_day_attempts=stats.attempts,seven_day_successes=stats.successes,
          seven_day_success_rate=CASE WHEN stats.attempts=0 THEN 1
            ELSE stats.successes::numeric/stats.attempts END,
          status=CASE WHEN s.resume_at IS NOT NULL AND s.resume_at<=NOW() THEN 'active' ELSE s.status END,
          resume_at=CASE WHEN s.resume_at IS NOT NULL AND s.resume_at<=NOW() THEN NULL ELSE s.resume_at END,
          updated_at=NOW() FROM stats WHERE stats.account_id=s.account_id"""))
        changed=(await db.execute(text("""WITH desired AS (
          SELECT s.account_id,s.tier current_tier,
            CASE WHEN (NOW()-s.platform_connected_at)<INTERVAL '16 days' THEN 1
                 WHEN (NOW()-s.platform_connected_at)<INTERVAL '31 days' THEN 2
                 WHEN (NOW()-s.platform_connected_at)<INTERVAL '61 days' THEN 3 ELSE 4 END desired_tier
          FROM video_reinvite_account_state s JOIN telegram_accounts a ON a.id=s.account_id
          WHERE NOT s.tier_locked AND a.status='connected' AND a.is_active
        ) UPDATE video_reinvite_account_state s SET
          tier=CASE WHEN d.desired_tier>s.tier AND s.status='active'
                          AND s.seven_day_success_rate>=0.95
                          AND (s.last_peer_flood_at IS NULL OR s.last_peer_flood_at<NOW()-INTERVAL '7 days')
                          AND (s.last_restricted_at IS NULL OR s.last_restricted_at<NOW()-INTERVAL '7 days')
                    THEN LEAST(d.desired_tier,s.tier+1)
                    WHEN d.desired_tier<s.tier THEN d.desired_tier ELSE s.tier END,
          tier_changed_at=CASE
            WHEN d.desired_tier>s.tier AND s.status='active'
                 AND s.seven_day_success_rate>=0.95
                 AND (s.last_peer_flood_at IS NULL OR s.last_peer_flood_at<NOW()-INTERVAL '7 days')
                 AND (s.last_restricted_at IS NULL OR s.last_restricted_at<NOW()-INTERVAL '7 days') THEN NOW()
            WHEN d.desired_tier<s.tier THEN NOW() ELSE s.tier_changed_at END,
          updated_at=NOW()
          FROM desired d WHERE d.account_id=s.account_id RETURNING s.account_id"""))).rowcount or 0
        await db.execute(text("""UPDATE video_reinvite_account_state SET
          effective_daily_limit=CASE
            WHEN tier=1 AND NOW()-first_connected_at<INTERVAL '1 day' THEN 5
            WHEN tier=1 AND NOW()-first_connected_at<INTERVAL '2 days' THEN 10
            WHEN tier=1 AND NOW()-first_connected_at<INTERVAL '3 days' THEN 15
            ELSE CEIL((CASE tier WHEN 1 THEN 15 WHEN 2 THEN 25 WHEN 3 THEN 40 ELSE 60 END) *
            CASE WHEN NOW()-tier_changed_at<INTERVAL '1 day' THEN 0.5
                 WHEN NOW()-tier_changed_at<INTERVAL '2 days' THEN 0.75 ELSE 1 END)
          END,
          effective_min_interval_seconds=CASE tier WHEN 1 THEN 180 WHEN 2 THEN 150 WHEN 3 THEN 120 ELSE 90 END,
          updated_at=NOW()"""))
        await db.commit()
        return {"evaluated": changed}


def _next_round_time(round_number: int, round_days: list[int]) -> datetime | None:
    if round_number >= len(round_days):
        return None
    previous_day = round_days[round_number - 1] if round_number else 0
    delay_days = max(1, round_days[round_number] - previous_day)
    return datetime.now(timezone.utc) + timedelta(days=delay_days)


async def mark_video_reinvite_reply(db: Any, *, user_id: str, account_id: str, chat_id: int) -> bool:
    row = (
        await db.execute(
            text(
                """
                UPDATE video_reinvite_jobs
                SET status='replied', replied_at=NOW(), next_send_at=NULL,
                    stopped_reason='user_replied', updated_at=NOW()
                WHERE user_id=CAST(:user_id AS uuid)
                  AND last_sent_at IS NOT NULL
                  AND status IN ('scheduled','sent','restricted','stopped')
                RETURNING id
                """
            ),
            {"user_id": user_id},
        )
    ).first()
    if row:
        logger.bind(user_id=user_id, account_id=account_id, chat_id=chat_id).info(
            "video_reinvite.user_replied"
        )
    return bool(row)


async def _load_settings(db: Any) -> dict[str, Any] | None:
    row = (
        await db.execute(text("SELECT * FROM video_reinvite_settings WHERE id=1"))
    ).mappings().first()
    return dict(row) if row and row["enabled"] else None


async def _sync_jobs(db: Any) -> dict[str, int]:
    # A completed video call is terminal regardless of how it was answered.
    completed = await db.execute(
        text(
            """
            WITH completed_calls AS (
              SELECT DISTINCT ON (user_id) user_id, ended_at
              FROM call_broadcast_jobs
              WHERE status='completed' AND video_asset_id IS NOT NULL AND started_at IS NOT NULL
              ORDER BY user_id, ended_at DESC NULLS LAST
            )
            UPDATE video_reinvite_jobs r
            SET status='video_success', video_success_at=COALESCE(video_success_at, j.ended_at, NOW()),
                next_send_at=NULL, stopped_reason='video_completed', updated_at=NOW()
            FROM completed_calls j
            WHERE j.user_id=r.user_id::text AND r.status <> 'video_success'
            """
        )
    )
    # Human control means no automated follow-up.
    await db.execute(
        text(
            """
            UPDATE video_reinvite_jobs r
            SET status='paused', next_send_at=NULL, stopped_reason='human_takeover', updated_at=NOW()
            WHERE r.status IN ('scheduled','sent','restricted','waiting_migration')
              AND EXISTS (
                SELECT 1 FROM handoff_tasks h
                WHERE h.user_id=r.user_id AND h.status IN ('pending','assigned','in_progress')
              )
            """
        )
    )
    # Refresh the safest reachable account from the peer cache.
    await db.execute(
        text(
            """
            WITH candidates AS (
              SELECT r.id,r.user_id
              FROM video_reinvite_jobs r
              WHERE r.status='waiting_migration' OR r.account_id IS NULL
              ORDER BY r.updated_at
              LIMIT 500
            ), targets AS (
              SELECT c.id,p.account_id,p.conversation_id,p.chat_id,p.access_hash
              FROM candidates c
              JOIN LATERAL (
                SELECT pc.account_id,pc.conversation_id,pc.chat_id,pc.access_hash
                FROM telegram_peer_cache pc
                JOIN telegram_accounts ta ON ta.id=pc.account_id
                WHERE pc.user_id=c.user_id
                  AND ta.status='connected' AND ta.is_active
                ORDER BY pc.last_seen_at DESC
                LIMIT 1
              ) p ON TRUE
            )
            UPDATE video_reinvite_jobs r
            SET account_id=p.account_id, conversation_id=COALESCE(p.conversation_id,r.conversation_id),
                telegram_chat_id=p.chat_id, telegram_access_hash=p.access_hash,
                status=CASE WHEN r.status='waiting_migration' THEN 'scheduled' ELSE r.status END,
                updated_at=NOW()
            FROM targets p
            WHERE p.id=r.id
            """
        )
    )
    created = await db.execute(
        text(
            """
            WITH candidate_users AS (
              SELECT u.*
              FROM users u
              WHERE u.channel='telegram_real_user'
                AND u.created_at <= (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day'
                AND COALESCE(u.status,'active') NOT IN ('blocked','banned','deleted')
                AND NOT EXISTS (SELECT 1 FROM video_reinvite_jobs r WHERE r.user_id=u.id)
                AND NOT EXISTS (
                  SELECT 1 FROM call_broadcast_jobs j
                  WHERE j.user_id=u.id::text AND j.status='completed'
                    AND j.video_asset_id IS NOT NULL AND j.started_at IS NOT NULL
                )
              ORDER BY u.created_at
              LIMIT 500
            )
            INSERT INTO video_reinvite_jobs
              (user_id, conversation_id, account_id, telegram_chat_id,
               telegram_access_hash, status, next_send_at, metadata)
            SELECT u.id, p.conversation_id, p.account_id, p.chat_id, p.access_hash,
                   CASE WHEN p.account_id IS NULL THEN 'waiting_migration' ELSE 'scheduled' END,
                   CASE WHEN p.account_id IS NULL THEN NULL
                        ELSE GREATEST(NOW(), u.created_at AT TIME ZONE 'UTC' + INTERVAL '1 day') END,
                   jsonb_build_object('cohort_created_at', u.created_at)
            FROM candidate_users u
            LEFT JOIN LATERAL (
              SELECT pc.account_id, pc.conversation_id, pc.chat_id, pc.access_hash
              FROM telegram_peer_cache pc JOIN telegram_accounts ta ON ta.id=pc.account_id
              WHERE pc.user_id=u.id AND ta.status='connected' AND ta.is_active
              ORDER BY pc.last_seen_at DESC LIMIT 1
            ) p ON TRUE
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    )
    return {"created": created.rowcount or 0, "completed": completed.rowcount or 0}


async def _claim_one(db: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    bj_hour = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).hour
    if not (int(settings["send_hour_start"]) <= bj_hour < int(settings["send_hour_end"])):
        return None
    # The API runs multiple worker processes. This database gate is atomic
    # across all of them and enforces one global claim per minute.
    gate = (
        await db.execute(
            text(
                """
                UPDATE video_reinvite_settings
                SET next_global_send_at=NOW()+INTERVAL '1 minute',updated_at=NOW()
                WHERE id=1 AND enabled
                  AND (next_global_send_at IS NULL OR next_global_send_at <= NOW())
                  AND NOT EXISTS (
                    SELECT 1 FROM message_schedules ms WHERE ms.status='pending'
                      AND ms.invitation_queue IN ('P1','P2')
                      AND (ms.send_at IS NULL OR ms.send_at<=NOW())
                  )
                  AND NOT (
                    MOD(FLOOR(EXTRACT(EPOCH FROM NOW())/60)::bigint,20)=19
                    AND EXISTS (SELECT 1 FROM message_schedules p4 WHERE p4.status='pending'
                      AND p4.invitation_queue='P4' AND (p4.send_at IS NULL OR p4.send_at<=NOW()))
                    AND (SELECT COUNT(*) FROM message_schedules d WHERE d.status='sent' AND d.invitation_queue='P4'
                      AND d.sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')<36
                  )
                RETURNING id
                """
            )
        )
    ).first()
    if not gate:
        return None
    row = (
        await db.execute(
            text(
                """
                WITH candidate AS (
                  SELECT r.id
                  FROM video_reinvite_jobs r JOIN telegram_accounts ta ON ta.id=r.account_id
                  JOIN video_reinvite_account_state ast ON ast.account_id=r.account_id
                  WHERE r.status IN ('scheduled','sent','restricted') AND r.next_send_at <= NOW()
                    AND ta.status='connected' AND ta.is_active
                    AND ast.status='active'
                    AND ast.health_check_status='healthy'
                    AND ast.last_health_check_at >= date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'
                    AND r.round_number < :max_rounds
                    AND (
                      SELECT COUNT(*) FROM video_reinvite_attempts a
                      WHERE a.account_id=r.account_id AND a.status='sent'
                        AND a.sent_at >= date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'
                    ) < ast.effective_daily_limit
                    AND NOT EXISTS (
                      SELECT 1 FROM video_reinvite_attempts a
                      WHERE a.account_id=r.account_id
                        AND a.created_at >= NOW() - make_interval(secs => ast.effective_min_interval_seconds)
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM conversations c JOIN messages m ON m.conversation_id=c.id
                      WHERE c.user_id=r.user_id AND m.sender_type='assistant'
                        AND m.created_at >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM call_broadcast_jobs j
                      WHERE j.user_id=r.user_id::text
                        AND j.status NOT IN ('completed','failed','cancelled')
                    )
                  ORDER BY (
                    SELECT COUNT(*)::numeric/GREATEST(ast.effective_daily_limit,1)
                    FROM video_reinvite_attempts a WHERE a.account_id=r.account_id AND a.status='sent'
                      AND a.sent_at >= date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'
                  ), ast.tier DESC, r.next_send_at, r.created_at
                  FOR UPDATE OF r SKIP LOCKED LIMIT 1
                )
                UPDATE video_reinvite_jobs r SET status='sending', updated_at=NOW()
                FROM candidate c WHERE r.id=c.id
                RETURNING r.id::text,r.user_id::text,r.account_id::text,r.telegram_chat_id,
                          r.telegram_access_hash,r.round_number
                """
            ),
            {"max_rounds": int(settings["max_rounds"])},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _send(job: dict[str, Any], settings: dict[str, Any]) -> None:
    job_id = job["id"]
    next_round = int(job["round_number"]) + 1
    attempt_id: str | None = None
    try:
        account_id = UUID(job["account_id"])
        from services.runtime_ownership import legacy_worker_should_handle_account

        if not await legacy_worker_should_handle_account(str(account_id)):
            logger.bind(job_id=job_id, account_id=str(account_id)).info(
                "video_reinvite.skip_runtime_owned"
            )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text(
                        """
                        UPDATE video_reinvite_jobs
                           SET status = CASE WHEN round_number > 0 THEN 'sent' ELSE 'scheduled' END,
                               next_send_at = NOW(),
                               updated_at = NOW()
                         WHERE id = CAST(:id AS uuid)
                           AND status = 'sending'
                        """
                    ),
                    {"id": job_id},
                )
                await db.commit()
            return
        client = await telegram_account_manager.get_client(account_id)
        if client is None:
            raise RuntimeError("account_not_connected")
        peer = await resolve_telethon_peer(
            client, int(job["telegram_chat_id"]), access_hash=job.get("telegram_access_hash")
        )
        async with AsyncSessionLocal() as db:
            attempt_id = (
                await db.execute(
                    text("INSERT INTO video_reinvite_attempts(job_id,round_number,account_id,status) VALUES(CAST(:job AS uuid),:round,CAST(:account AS uuid),'sending') RETURNING id::text"),
                    {"job": job_id, "round": next_round, "account": job["account_id"]},
                )
            ).scalar_one()
            await db.commit()
        sent = await client.send_message(peer, str(settings["invitation_message"]))
        round_days = list(settings["round_days"] or [1, 3, 7])
        next_at = _next_round_time(next_round, round_days)
        terminal = next_round >= int(settings["max_rounds"])
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE video_reinvite_attempts SET status='sent',telegram_message_id=:mid,sent_at=NOW() WHERE id=CAST(:id AS uuid)"), {"id": attempt_id, "mid": getattr(sent, "id", None)})
            await db.execute(text("""INSERT INTO video_reinvite_account_state(account_id,status,consecutive_failures,last_success_at)
              VALUES(CAST(:account AS uuid),'active',0,NOW()) ON CONFLICT(account_id) DO UPDATE
              SET status='active',consecutive_failures=0,paused_at=NULL,pause_reason=NULL,
                  resume_at=NULL,last_success_at=NOW(),updated_at=NOW()"""), {"account":job["account_id"]})
            await db.execute(
                text("""UPDATE video_reinvite_jobs SET status=:status,round_number=:round,last_sent_at=NOW(),
                     next_send_at=:next_at, failure_reason=NULL,
                     stopped_reason=CASE WHEN :terminal THEN 'max_rounds_sent' ELSE NULL END,updated_at=NOW()
                     WHERE id=CAST(:id AS uuid)"""),
                {"id": job_id, "status": "stopped" if terminal else "sent", "round": next_round,
                 "next_at": next_at, "terminal": terminal},
            )
            await db.commit()
        logger.bind(job_id=job_id, round_number=next_round).info("video_reinvite.sent")
    except Exception as exc:
        lowered = f"{type(exc).__name__} {exc}".lower()
        is_peer_flood = any(x in lowered for x in ("peerflood", "floodwait", "flood wait"))
        is_restricted = any(x in lowered for x in ("spam", "restricted")) and not is_peer_flood
        unreachable = any(x in lowered for x in ("blocked", "privacy", "deactivated"))
        status = "restricted" if is_peer_flood or is_restricted else "unreachable" if unreachable else "scheduled"
        retry_seconds = 86400 if is_peer_flood else 604800 if is_restricted else 86400 if unreachable else 1800
        async with AsyncSessionLocal() as db:
            await db.execute(text("""UPDATE video_reinvite_jobs SET status=:status,next_send_at=NOW()+make_interval(secs=>:retry),failure_reason=:reason,updated_at=NOW() WHERE id=CAST(:id AS uuid)"""), {"id": job_id,"status": status,"retry": retry_seconds,"reason": str(exc)[:500]})
            attempt_status = "restricted" if status == "restricted" else "unreachable" if status == "unreachable" else "failed"
            if attempt_id:
                await db.execute(text("""UPDATE video_reinvite_attempts SET status=:status,
                  failure_reason=:reason WHERE id=CAST(:id AS uuid)"""),
                  {"id":attempt_id,"status":attempt_status,"reason":str(exc)[:500]})
            else:
                await db.execute(text("""INSERT INTO video_reinvite_attempts(job_id,round_number,account_id,status,failure_reason) VALUES(CAST(:job AS uuid),:round,CAST(:account AS uuid),:status,:reason)"""), {"job": job_id,"round": next_round,"account": job["account_id"],"status": attempt_status,"reason": str(exc)[:500]})
            # A recipient blocking/deactivating chat is not an account-health
            # failure and must never downgrade or pause the sending account.
            if unreachable:
                await db.commit()
                logger.bind(job_id=job_id,error_type=type(exc).__name__).warning("video_reinvite.unreachable")
                return
            state = (await db.execute(text("""INSERT INTO video_reinvite_account_state
              (account_id,status,consecutive_failures,last_failure_at)
              VALUES(CAST(:account AS uuid),'active',1,NOW())
              ON CONFLICT(account_id) DO UPDATE SET consecutive_failures=video_reinvite_account_state.consecutive_failures+1,
                last_failure_at=NOW(),updated_at=NOW()
              RETURNING consecutive_failures,tier"""), {"account":job["account_id"]})).mappings().one()
            failures = int(state["consecutive_failures"])
            if is_restricted:
                pause_reason, resume_seconds, new_tier = "spam_or_account_restricted", 604800, 1
            elif is_peer_flood:
                pause_reason, resume_seconds, new_tier = "peer_flood", 86400, max(1, int(state["tier"])-1)
            elif failures >= 2:
                pause_reason, resume_seconds, new_tier = "two_consecutive_send_failures", None, int(state["tier"])
            else:
                pause_reason, resume_seconds, new_tier = "single_send_failure_observation", 1800, int(state["tier"])
            if pause_reason:
                await db.execute(text("""UPDATE video_reinvite_account_state SET
                  status=CASE WHEN :reason='single_send_failure_observation' THEN 'observing' ELSE 'paused' END,
                  paused_at=NOW(),pause_reason=:reason,
                  resume_at=CASE WHEN CAST(:resume AS integer) IS NULL THEN NULL ELSE NOW()+make_interval(secs=>CAST(:resume AS integer)) END,
                  tier=:tier,tier_changed_at=CASE WHEN tier<>:tier THEN NOW() ELSE tier_changed_at END,
                  last_peer_flood_at=CASE WHEN :reason='peer_flood' THEN NOW() ELSE last_peer_flood_at END,
                  last_restricted_at=CASE WHEN :reason='spam_or_account_restricted' THEN NOW() ELSE last_restricted_at END,
                  updated_at=NOW() WHERE account_id=CAST(:account AS uuid)"""),
                  {"account":job["account_id"],"reason":pause_reason,"resume":resume_seconds,"tier":new_tier})
                await db.execute(text("""UPDATE video_reinvite_jobs SET status='restricted',
                  next_send_at=CASE WHEN CAST(:resume AS integer) IS NULL THEN NULL ELSE NOW()+make_interval(secs=>CAST(:resume AS integer)) END,
                  stopped_reason=:reason,updated_at=NOW()
                  WHERE account_id=CAST(:account AS uuid) AND status IN ('scheduled','sent','restricted')"""),
                  {"account":job["account_id"],"reason":pause_reason,"resume":resume_seconds})
            await db.commit()
        logger.bind(job_id=job_id,error_type=type(exc).__name__).warning("video_reinvite.failed")


async def run_one_tick() -> dict[str, int]:
    if _tick_lock.locked():
        return {"claimed": 0}
    async with _tick_lock:
        async with AsyncSessionLocal() as db:
            # Every API/runtime worker starts its own scheduler. Serialize the
            # expensive sync across processes and cap it below the tick period.
            acquired = (
                await db.execute(
                    text("SELECT pg_try_advisory_xact_lock(6300430)")
                )
            ).scalar()
            if not acquired:
                await db.rollback()
                return {"claimed": 0, "busy": 1}
            await db.execute(text("SET LOCAL statement_timeout = '50s'"))
            await db.execute(text("SET LOCAL lock_timeout = '3s'"))
            settings = await _load_settings(db)
            if not settings:
                return {"claimed": 0}
            sync = await _sync_jobs(db)
            job = await _claim_one(db, settings)
            await db.commit()
        if job:
            await _send(job, settings)
        return {"claimed": int(bool(job)), **sync}


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    scheduler = AsyncIOScheduler(timezone="UTC")
    # One user globally per minute. Account-level guards remain in place, so
    # this is stricter than the approved one-user-per-account-per-minute cap.
    scheduler.add_job(run_one_tick,"interval",seconds=60,id=JOB_ID,max_instances=1,coalesce=True)
    scheduler.add_job(evaluate_account_tiers,"cron",hour=9,minute=30,timezone="Asia/Shanghai",
                      id="video-reinvite-tier-evaluation",max_instances=1,coalesce=True)
    for hour,minute,label in ((9,0,"full"),(9,10,"recheck"),(9,20,"confirm"),(14,0,"incremental"),(18,0,"incremental-evening"),(21,50,"final")):
        scheduler.add_job(run_health_check,"cron",hour=hour,minute=minute,timezone="Asia/Shanghai",
                          args=[label],id=f"telegram-health-{label}",max_instances=1,coalesce=True)
    scheduler.start()
    _scheduler=scheduler
    logger.info("video_reinvite.scheduler.started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler=None
