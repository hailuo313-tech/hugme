from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from services.telegram_account_health import queue_health_check

router = APIRouter()


class SettingsUpdate(BaseModel):
    enabled: bool
    invitation_message: str = Field(min_length=1, max_length=2000)
    send_hour_start: int = Field(default=10, ge=0, le=23)
    send_hour_end: int = Field(default=22, ge=1, le=24)
    daily_account_limit: int = Field(default=15, ge=1, le=50)


class TierUpdate(BaseModel):
    tier: int = Field(ge=1, le=4)
    locked: bool = True


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    settings = (await db.execute(text("SELECT * FROM video_reinvite_settings WHERE id=1"))).mappings().one()
    counts = (await db.execute(text("""SELECT COUNT(*) total,
      COUNT(*) FILTER(WHERE status IN ('scheduled','sent')) pending,
      COUNT(*) FILTER(WHERE status='replied') replied,
      COUNT(*) FILTER(WHERE status='video_success') video_success,
      COUNT(*) FILTER(WHERE status='restricted') restricted,
      COUNT(*) FILTER(WHERE status='waiting_migration') waiting_migration,
      COUNT(*) FILTER(WHERE status='paused') paused,
      COUNT(*) FILTER(WHERE status='stopped') stopped,
      COUNT(*) FILTER(WHERE last_sent_at::date=(NOW() AT TIME ZONE 'Asia/Shanghai')::date) sent_today,
      (SELECT COUNT(*) FROM video_reinvite_account_state s WHERE s.status='paused') paused_accounts
      FROM video_reinvite_jobs"""))).mappings().one()
    queue_counts=(await db.execute(text("""SELECT
      COUNT(*) FILTER(WHERE invitation_queue='P1' AND status='pending') p1_pending,
      COUNT(*) FILTER(WHERE invitation_queue='P2' AND status='pending') p2_pending,
      (SELECT COUNT(*) FROM video_reinvite_jobs WHERE status IN ('scheduled','sent','restricted')) p3_pending,
      COUNT(*) FILTER(WHERE invitation_queue='P4' AND status='pending') p4_pending,
      COUNT(*) FILTER(WHERE invitation_queue='P4' AND status='sent' AND
        sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai') p4_sent_today
      FROM message_schedules"""))).mappings().one()
    return {"settings": dict(settings), "counts": {**dict(counts),**dict(queue_counts)}}


@router.put("/settings")
async def update_settings(payload: SettingsUpdate, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    await db.execute(text("""UPDATE video_reinvite_settings SET enabled=:enabled,
      invitation_message=:message,send_hour_start=:start,send_hour_end=:end,
      min_interval_seconds=180,max_interval_seconds=180,hourly_account_limit=:limit,
      daily_account_limit=:limit,updated_at=NOW() WHERE id=1"""),
      {"enabled":payload.enabled,"message":payload.invitation_message.strip(),"start":payload.send_hour_start,"end":payload.send_hour_end,"limit":payload.daily_account_limit})
    await db.commit()
    return {"ok": True}


@router.get("/jobs")
async def list_jobs(status: str | None = None, search: str | None = None,
                    limit: int = Query(200,ge=1,le=1000), db: AsyncSession = Depends(get_db),
                    _operator: Any = Depends(require_operator)):
    search_like=f"%{search.strip()}%" if search and search.strip() else None
    rows=(await db.execute(text("""SELECT r.id::text,r.user_id::text,u.nickname,u.external_id,
      r.status,r.round_number,r.next_send_at,r.last_sent_at,r.replied_at,r.video_success_at,
      r.stopped_reason,r.failure_reason,COALESCE(ta.display_name,ta.username,ta.phone) account
      FROM video_reinvite_jobs r JOIN users u ON u.id=r.user_id
      LEFT JOIN telegram_accounts ta ON ta.id=r.account_id
      WHERE (CAST(:status AS text) IS NULL OR r.status=CAST(:status AS text))
        AND (CAST(:search AS text) IS NULL OR u.nickname ILIKE CAST(:search AS text) OR u.external_id ILIKE CAST(:search AS text))
      ORDER BY COALESCE(r.next_send_at,r.updated_at) DESC LIMIT :limit"""),
      {"status":status,"search":search_like,"limit":limit})).mappings().all()
    return {"items":[dict(x) for x in rows]}


@router.post("/jobs/{job_id}/pause")
async def pause(job_id: UUID, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    await db.execute(text("UPDATE video_reinvite_jobs SET status='paused',next_send_at=NULL,stopped_reason='operator_paused',updated_at=NOW() WHERE id=CAST(:id AS uuid)"),{"id":str(job_id)})
    await db.commit(); return {"ok":True}


@router.get("/account-states")
async def account_states(db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    rows=(await db.execute(text("""SELECT s.account_id::text,a.username,
      s.status,s.consecutive_failures,s.paused_at,s.pause_reason,s.resume_at,
      s.last_success_at,s.last_failure_at,s.platform_connected_at,
      GREATEST(0,FLOOR(EXTRACT(EPOCH FROM (NOW()-s.platform_connected_at))/86400))::int connection_days,
      s.tier,s.tier_locked,s.effective_daily_limit,s.effective_min_interval_seconds,
      s.seven_day_attempts,s.seven_day_successes,s.seven_day_success_rate,
      s.last_peer_flood_at,s.last_restricted_at,
      CASE
        WHEN s.health_check_status='banned' THEN 'banned'
        WHEN s.health_check_status='restricted'
          OR (s.status='paused' AND (
            s.last_peer_flood_at IS NOT NULL OR s.last_restricted_at IS NOT NULL
            OR COALESCE(s.pause_reason,'') ~* 'peerflood|flood|spam|restrict'
          )) THEN 'restricted'
        WHEN s.health_check_status='pending_recheck'
          OR COALESCE(s.consecutive_failures,0)>0 THEN 'pending_recheck'
        ELSE 'healthy'
      END AS health_check_status,
      s.last_health_check_at,s.last_health_error,s.health_check_attempts,s.is_new_account,
      COALESCE(
        s.last_health_error,
        s.pause_reason,
        CASE WHEN COALESCE(s.consecutive_failures,0)>0
          THEN '连续发送失败 ' || s.consecutive_failures::text || ' 次，需复查' END
      ) AS health_display_error,
      COALESCE(uc.user_count,0) AS user_count,
      COALESCE(uc.active_today,0) AS active_today
      FROM video_reinvite_account_state s JOIN telegram_accounts a ON a.id=s.account_id
      LEFT JOIN (
        SELECT account_id,
          COUNT(DISTINCT user_id) AS user_count,
          COUNT(DISTINCT user_id) FILTER (
            WHERE last_seen_at >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'
          ) AS active_today
        FROM telegram_peer_cache
        WHERE user_id IS NOT NULL
        GROUP BY account_id
      ) uc ON uc.account_id=s.account_id
      ORDER BY (s.health_check_status='banned') DESC,(s.status='paused') DESC,
        (COALESCE(s.consecutive_failures,0)>0) DESC,COALESCE(uc.user_count,0) DESC,s.updated_at DESC"""))).mappings().all()
    return {"items":[dict(x) for x in rows]}


@router.get("/health-checks/overview")
async def health_check_overview(db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    latest=(await db.execute(text("SELECT * FROM telegram_account_health_runs ORDER BY started_at DESC LIMIT 1"))).mappings().first()
    counts=(await db.execute(text("""WITH classified AS (
      SELECT is_new_account,
        CASE
          WHEN health_check_status='banned' THEN 'banned'
          WHEN health_check_status='restricted'
            OR (status='paused' AND (
              last_peer_flood_at IS NOT NULL OR last_restricted_at IS NOT NULL
              OR COALESCE(pause_reason,'') ~* 'peerflood|flood|spam|restrict'
            )) THEN 'restricted'
          WHEN health_check_status='pending_recheck'
            OR COALESCE(consecutive_failures,0)>0 THEN 'pending_recheck'
          ELSE 'healthy'
        END AS effective_health
      FROM video_reinvite_account_state
    ) SELECT COUNT(*) total,
      COUNT(*) FILTER(WHERE effective_health='healthy') healthy,
      COUNT(*) FILTER(WHERE effective_health='pending_recheck') pending,
      COUNT(*) FILTER(WHERE effective_health='restricted') restricted,
      COUNT(*) FILTER(WHERE effective_health='banned') banned,
      COUNT(*) FILTER(WHERE is_new_account) new_accounts,
      COALESCE((
        SELECT COUNT(DISTINCT p.user_id)
        FROM telegram_peer_cache p
        JOIN video_reinvite_account_state vs ON vs.account_id=p.account_id
        WHERE p.user_id IS NOT NULL
      ),0) AS user_total,
      COALESCE((
        SELECT COUNT(DISTINCT p.user_id)
        FROM telegram_peer_cache p
        JOIN video_reinvite_account_state vs ON vs.account_id=p.account_id
        WHERE p.user_id IS NOT NULL
          AND p.last_seen_at >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'
      ),0) AS active_today
      FROM classified"""))).mappings().one()
    return {"latest":dict(latest) if latest else None,"counts":dict(counts),
            "schedule":["09:00 全量","09:10 复查","09:20 确认","14:00 增量","18:00 增量","21:50 最终"]}


@router.post("/health-checks/run")
async def trigger_health_check(_operator: Any = Depends(require_operator)):
    result = await queue_health_check("manual")
    return result


@router.post("/account-states/{account_id}/resume")
async def resume_account(account_id: UUID, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    await db.execute(text("""INSERT INTO video_reinvite_account_state(account_id,status,consecutive_failures)
      VALUES(CAST(:id AS uuid),'active',0) ON CONFLICT(account_id) DO UPDATE SET status='active',
      consecutive_failures=0,paused_at=NULL,pause_reason=NULL,resume_at=NULL,updated_at=NOW()"""),{"id":str(account_id)})
    await db.execute(text("""UPDATE video_reinvite_jobs SET status='scheduled',next_send_at=NOW(),
      stopped_reason=NULL,updated_at=NOW() WHERE account_id=CAST(:id AS uuid) AND status='restricted'
      AND stopped_reason='account_consecutive_failures'"""),{"id":str(account_id)})
    await db.commit(); return {"ok":True}


@router.post("/account-states/{account_id}/pause")
async def pause_account(account_id: UUID, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    await db.execute(text("""UPDATE video_reinvite_account_state SET status='paused',paused_at=NOW(),
      pause_reason='operator_paused',resume_at=NULL,updated_at=NOW() WHERE account_id=CAST(:id AS uuid)"""),{"id":str(account_id)})
    await db.commit(); return {"ok":True}


@router.put("/account-states/{account_id}/tier")
async def set_account_tier(account_id: UUID, payload: TierUpdate, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    limits={1:(15,180),2:(25,150),3:(40,120),4:(60,90)}
    daily,interval=limits[payload.tier]
    await db.execute(text("""UPDATE video_reinvite_account_state SET tier=:tier,tier_locked=:locked,
      tier_changed_at=NOW(),effective_daily_limit=:daily,effective_min_interval_seconds=:interval,
      updated_at=NOW() WHERE account_id=CAST(:id AS uuid)"""),
      {"id":str(account_id),"tier":payload.tier,"locked":payload.locked,"daily":daily,"interval":interval})
    await db.commit(); return {"ok":True}


@router.post("/jobs/{job_id}/resume")
async def resume(job_id: UUID, db: AsyncSession = Depends(get_db), _operator: Any = Depends(require_operator)):
    await db.execute(text("UPDATE video_reinvite_jobs SET status='scheduled',next_send_at=NOW(),stopped_reason=NULL,updated_at=NOW() WHERE id=CAST(:id AS uuid) AND status IN ('paused','restricted','unreachable')"),{"id":str(job_id)})
    await db.commit(); return {"ok":True}
