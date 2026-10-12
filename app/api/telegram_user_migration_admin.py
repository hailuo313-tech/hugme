from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.config import settings
from core.database import get_db

router = APIRouter()
MIGRATION_IMAGE_DIR = Path(settings.MEDIA_UPLOAD_DIR) / "telegram-user-migration"
MIGRATION_DRAFT_FILE = MIGRATION_IMAGE_DIR / "draft.json"
MAX_MIGRATION_IMAGE_BYTES = 10 * 1024 * 1024
MIGRATION_IMAGE_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
}


class CampaignCreate(BaseModel):
    source_account_id: UUID
    target_account_id: UUID
    name: str = Field(min_length=1, max_length=120)
    intro_message: str = Field(min_length=1, max_length=2000)
    rate_per_minute: int = Field(default=5, ge=1, le=30)
    user_ids: list[UUID] = Field(min_length=1, max_length=5000)
    filters: dict[str, Any] = Field(default_factory=dict)
    image_path: str


class CampaignDraft(BaseModel):
    name: str = Field(default="", max_length=120)
    intro_message: str = Field(default="", max_length=1024)
    rate_per_minute: int = Field(default=1, ge=1, le=30)
    image_path: str | None = None
    image_filename: str | None = None


def _operator_id(operator: Any) -> str | None:
    if isinstance(operator, dict):
        return str(operator.get("operator_id") or operator.get("id") or "") or None
    return str(getattr(operator, "operator_id", None) or getattr(operator, "id", None) or "") or None


def _validated_migration_image_path(value: str | None) -> str | None:
    if not value:
        return None
    root = MIGRATION_IMAGE_DIR.resolve()
    candidate = Path(value).resolve()
    if candidate.parent != root or candidate.suffix.lower() not in {".jpg", ".png"}:
        raise HTTPException(status_code=422, detail="迁移图片路径无效")
    if not candidate.is_file():
        raise HTTPException(status_code=422, detail="迁移图片不存在，请重新上传")
    return str(candidate)


@router.post("/campaign-images", status_code=status.HTTP_201_CREATED)
async def upload_campaign_image(
    file: UploadFile = File(...),
    _operator: Any = Depends(require_operator),
):
    media_type = str(file.content_type or "").lower()
    image_type = MIGRATION_IMAGE_TYPES.get(media_type)
    if image_type is None:
        raise HTTPException(status_code=422, detail="只支持 JPG 或 PNG 图片")
    suffix, signature = image_type
    content = await file.read(MAX_MIGRATION_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="图片文件为空")
    if len(content) > MAX_MIGRATION_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过10MB")
    if not content.startswith(signature):
        raise HTTPException(status_code=422, detail="图片内容与文件格式不一致")
    MIGRATION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = MIGRATION_IMAGE_DIR / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)
    return {"image_path": str(target), "filename": target.name,
            "image_url": f"/api/telegram-user-migration/admin/campaign-images/{target.name}"}


@router.get("/campaign-images/{filename}")
async def get_campaign_image(filename: str):
    candidate = (MIGRATION_IMAGE_DIR / Path(filename).name).resolve()
    if candidate.parent != MIGRATION_IMAGE_DIR.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="迁移图片不存在")
    return FileResponse(candidate)


@router.get("/draft")
async def get_campaign_draft(_operator: Any = Depends(require_operator)):
    if not MIGRATION_DRAFT_FILE.is_file():
        return {"name": "", "intro_message": "", "rate_per_minute": 1,
                "image_path": None, "image_filename": None, "image_url": None}
    try:
        data = __import__("json").loads(MIGRATION_DRAFT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    image_path = _validated_migration_image_path(data.get("image_path")) if data.get("image_path") else None
    filename = Path(image_path).name if image_path else None
    return {**data, "image_path": image_path, "image_filename": data.get("image_filename") or filename,
            "image_url": f"/api/telegram-user-migration/admin/campaign-images/{filename}" if filename else None}


@router.put("/draft")
async def save_campaign_draft(payload: CampaignDraft, _operator: Any = Depends(require_operator)):
    image_path = _validated_migration_image_path(payload.image_path) if payload.image_path else None
    MIGRATION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"name": payload.name, "intro_message": payload.intro_message,
            "rate_per_minute": payload.rate_per_minute, "image_path": image_path,
            "image_filename": payload.image_filename}
    temporary = MIGRATION_DRAFT_FILE.with_suffix(".tmp")
    temporary.write_text(__import__("json").dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(MIGRATION_DRAFT_FILE)
    return {"saved": True}


@router.get("/monitoring")
async def migration_monitoring(
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    summary = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM telegram_user_migration_campaigns WHERE status='running') AS running_campaigns,
                  COUNT(*) FILTER (WHERE status IN ('pending','resolving','resolved','sending','retry_wait')) AS waiting_tasks,
                  COUNT(*) FILTER (WHERE failure_code='no_safe_target_available'
                                      AND status IN ('pending','retry_wait')) AS waiting_safe_target,
                  COUNT(*) FILTER (WHERE sent_at>=NOW()-INTERVAL '1 hour') AS sent_last_hour,
                  COUNT(*) FILTER (WHERE sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                 AT TIME ZONE 'Asia/Shanghai') AS sent_today,
                  COUNT(*) FILTER (WHERE replied_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                    AT TIME ZONE 'Asia/Shanghai') AS success_today,
                  COUNT(*) FILTER (WHERE status IN ('failed','unreachable','restricted')
                                      AND updated_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                       AT TIME ZONE 'Asia/Shanghai') AS failed_today,
                  COUNT(*) FILTER (WHERE metadata->>'auto_assigned'='true'
                                      AND sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                   AT TIME ZONE 'Asia/Shanghai') AS auto_assigned_today
                FROM telegram_user_migration_tasks
                """
            )
        )
    ).mappings().one()
    tier_rows = (
        await db.execute(
            text(
                """
                WITH account_usage AS (
                  SELECT s.account_id, s.tier,
                    COUNT(t.id) FILTER (WHERE t.sent_at>=NOW()-INTERVAL '1 hour')::int AS sent_hour,
                    COUNT(t.id) FILTER (WHERE t.sent_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                       AT TIME ZONE 'Asia/Shanghai')::int AS sent_today,
                    MIN(t.sent_at) FILTER (WHERE t.sent_at IS NOT NULL) AS first_migration_at,
                    (a.status='connected' AND a.is_active AND s.status='active'
                      AND s.health_check_status='healthy'
                      AND s.last_health_check_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                    AT TIME ZONE 'Asia/Shanghai'
                      AND (s.last_peer_flood_at IS NULL OR s.last_peer_flood_at<
                        date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')
                      AND (s.last_restricted_at IS NULL OR s.last_restricted_at<
                        date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')
                    ) AS eligible,
                    (s.last_peer_flood_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                   AT TIME ZONE 'Asia/Shanghai'
                      OR s.last_restricted_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                   AT TIME ZONE 'Asia/Shanghai') AS restricted_today
                  FROM video_reinvite_account_state s
                  JOIN telegram_accounts a ON a.id=s.account_id
                  LEFT JOIN telegram_user_migration_tasks t ON t.target_account_id=s.account_id
                  WHERE s.tier BETWEEN 1 AND 4
                  GROUP BY s.account_id,s.tier,a.status,a.is_active,s.status,s.health_check_status,
                           s.last_health_check_at,s.last_peer_flood_at,s.last_restricted_at
                )
                SELECT tier,
                  COUNT(*) FILTER (WHERE eligible)::int AS eligible_accounts,
                  COUNT(*) FILTER (WHERE restricted_today)::int AS restricted_accounts,
                  COALESCE(SUM(sent_hour) FILTER (WHERE eligible),0)::int AS sent_hour,
                  COALESCE(SUM(sent_today) FILTER (WHERE eligible),0)::int AS sent_today,
                  COALESCE(SUM(
                    GREATEST(0,(CASE tier WHEN 1 THEN 1 WHEN 2 THEN 2 WHEN 3 THEN 2 ELSE 3 END)-sent_hour)
                  ) FILTER (WHERE eligible),0)::int AS hourly_remaining,
                  COALESCE(SUM(
                    GREATEST(0,(CASE
                      WHEN first_migration_at IS NULL OR first_migration_at>NOW()-INTERVAL '3 days'
                        THEN CASE tier WHEN 1 THEN 3 WHEN 2 THEN 4 ELSE 5 END
                      ELSE CASE tier WHEN 1 THEN 10 WHEN 2 THEN 12 WHEN 3 THEN 14 ELSE 15 END
                    END)-sent_today)
                  ) FILTER (WHERE eligible),0)::int AS daily_remaining
                FROM account_usage GROUP BY tier ORDER BY tier
                """
            )
        )
    ).mappings().all()
    recent = (
        await db.execute(
            text(
                """
                SELECT t.id::text,u.nickname,u.external_id,t.status,t.sent_at,t.replied_at,
                       t.updated_at,t.failure_reason,t.metadata->>'auto_assigned' AS auto_assigned,
                       COALESCE(a.display_name,a.username,a.phone) AS target_account,
                       COALESCE(s.tier,1) AS target_tier
                FROM telegram_user_migration_tasks t
                JOIN users u ON u.id=t.user_id
                LEFT JOIN telegram_accounts a ON a.id=t.target_account_id
                LEFT JOIN video_reinvite_account_state s ON s.account_id=t.target_account_id
                ORDER BY t.updated_at DESC LIMIT 20
                """
            )
        )
    ).mappings().all()
    beijing_now = (
        await db.execute(text("SELECT NOW() AT TIME ZONE 'Asia/Shanghai'"))
    ).scalar_one()
    current_time = beijing_now.time()
    if current_time < __import__("datetime").time(10, 0) or current_time >= __import__("datetime").time(22, 0):
        execution_status = "outside_window"
    elif __import__("datetime").time(17, 30) <= current_time < __import__("datetime").time(18, 30):
        execution_status = "health_check_pause"
    else:
        execution_status = "active"
    return {
        "summary": dict(summary),
        "tiers": [dict(row) for row in tier_rows],
        "recent": [dict(row) for row in recent],
        "execution_status": execution_status,
        "beijing_time": beijing_now.isoformat(),
        "refresh_seconds": 10,
    }


@router.get("/accounts")
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT a.id::text, a.display_name, a.username, a.phone, a.status, a.is_active,
                       COALESCE(a.metadata->>'reply_mode', 'ai') AS reply_mode,
                       COALESCE((a.metadata->>'archived_deleted')::boolean, false) AS archived_deleted,
                       (a.metadata->>'reference_count')::integer AS historical_reference_count,
                       a.metadata->>'last_reference_at' AS last_reference_at,
                       a.last_connected_at, s.first_connected_at,
                       GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (NOW() - s.first_connected_at)) / 86400))::integer AS connection_days,
                       s.tier, s.effective_daily_limit, s.health_check_status,
                       s.last_health_check_at,
                       (s.health_check_status='banned' AND s.paused_at<
                         date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                         AT TIME ZONE 'Asia/Shanghai') AS migration_source_eligible,
                       (a.status='connected' AND a.is_active AND s.status='active'
                         AND s.health_check_status='healthy'
                         AND s.last_health_check_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                                   AT TIME ZONE 'Asia/Shanghai'
                         AND (s.last_peer_flood_at IS NULL OR s.last_peer_flood_at<
                           date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')
                         AND (s.last_restricted_at IS NULL OR s.last_restricted_at<
                           date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai')
                       ) AS migration_target_eligible
                FROM telegram_accounts a
                LEFT JOIN video_reinvite_account_state s ON s.account_id=a.id
                ORDER BY display_name NULLS LAST, phone
                """
            )
        )
    ).mappings().all()
    items = [dict(row) for row in rows]
    return {
        "source_accounts": [x for x in items if x.get("migration_source_eligible")],
        "target_accounts": [
            x for x in items
            if x.get("migration_target_eligible") and 1 <= (x.get("tier") or 1) <= 4
        ],
    }


@router.get("/candidates")
async def list_candidates(
    source_account_id: UUID,
    search: str | None = Query(default=None, max_length=100),
    active_days: int | None = Query(default=None, ge=1, le=3650),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    search_like = f"%{search.strip()}%" if search and search.strip() else None
    rows = (
        await db.execute(
            text(
                """
                WITH account_users AS (
                    SELECT DISTINCT ON (p.user_id)
                      p.user_id, p.conversation_id, p.chat_id, p.access_hash, p.last_seen_at
                    FROM telegram_peer_cache p
                    WHERE p.account_id = CAST(:source_account_id AS uuid)
                      AND p.user_id IS NOT NULL
                    ORDER BY p.user_id, p.last_seen_at DESC
                ), historical_sources AS (
                    SELECT al.user_id, al.conversation_id, al.created_at AS last_seen_at
                    FROM attribution_links al
                    WHERE al.sender_account_id=:source_account_text
                      AND al.user_id IS NOT NULL
                    UNION ALL
                    SELECT c.user_id, c.id AS conversation_id, MAX(m.created_at) AS last_seen_at
                    FROM messages m
                    JOIN conversations c ON c.id=m.conversation_id
                    WHERE m.sender_type='assistant'
                      AND m.sender_id=:source_account_text
                      AND c.user_id IS NOT NULL
                    GROUP BY c.user_id, c.id
                ), historical_users AS (
                    SELECT DISTINCT ON (hs.user_id)
                      hs.user_id,
                      hs.conversation_id,
                      CASE WHEN u.external_id ~ '^tg_[0-9]+$'
                           THEN substring(u.external_id FROM 4)::bigint END AS chat_id,
                      NULL::bigint AS access_hash,
                      hs.last_seen_at
                    FROM historical_sources hs
                    JOIN users u ON u.id=hs.user_id
                    ORDER BY hs.user_id, hs.last_seen_at DESC
                ), latest_peer AS (
                    SELECT DISTINCT ON (x.user_id) x.*
                    FROM (
                      SELECT ap.*, 1 AS priority FROM account_users ap
                      UNION ALL
                      SELECT hu.*, 2 AS priority FROM historical_users hu
                    ) x
                    WHERE x.chat_id IS NOT NULL
                    ORDER BY x.user_id, x.priority, x.last_seen_at DESC
                )
                SELECT u.id::text AS user_id, u.external_id, u.nickname, u.language,
                       u.status, u.risk_level, lp.conversation_id::text,
                       lp.chat_id, lp.access_hash, lp.last_seen_at,
                       c.last_message_at,
                       EXISTS (
                         SELECT 1 FROM telegram_user_migration_tasks mt
                         WHERE mt.source_account_id = CAST(:source_account_id AS uuid)
                           AND mt.user_id = u.id
                           AND mt.status NOT IN ('failed','cancelled','unreachable')
                       ) AS already_migrating
                FROM latest_peer lp
                JOIN users u ON u.id = lp.user_id
                LEFT JOIN conversations c ON c.id = lp.conversation_id
                WHERE (CAST(:search AS text) IS NULL
                       OR u.external_id ILIKE CAST(:search AS text)
                       OR u.nickname ILIKE CAST(:search AS text))
                  AND (CAST(:active_days AS integer) IS NULL
                       OR COALESCE(c.last_message_at, lp.last_seen_at) >=
                          NOW() - make_interval(days => CAST(:active_days AS integer)))
                ORDER BY COALESCE(c.last_message_at, lp.last_seen_at) DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"source_account_id": str(source_account_id), "source_account_text": str(source_account_id), "search": search_like, "active_days": active_days, "limit": limit, "offset": offset},
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset}


@router.post("/campaigns")
async def create_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    operator: Any = Depends(require_operator),
):
    if payload.source_account_id == payload.target_account_id:
        raise HTTPException(status_code=400, detail="接管账号不能与被封账号相同")
    account_rows = (
        await db.execute(
            text(
                """
                SELECT a.id::text, a.status, a.is_active, COALESCE(s.tier, 1) AS tier,
                       s.status AS migration_status, s.health_check_status,
                       s.last_health_check_at, s.last_peer_flood_at, s.last_restricted_at,
                       s.paused_at
                FROM telegram_accounts a
                LEFT JOIN video_reinvite_account_state s ON s.account_id=a.id
                WHERE a.id IN (CAST(:source AS uuid), CAST(:target AS uuid))
                """
            ),
            {"source": str(payload.source_account_id), "target": str(payload.target_account_id)},
        )
    ).mappings().all()
    by_id = {row["id"]: row for row in account_rows}
    source = by_id.get(str(payload.source_account_id))
    beijing_day_start = (
        await db.execute(text("SELECT date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'"))
    ).scalar_one()
    if not source or source["health_check_status"] != "banned" or not source["paused_at"] or source["paused_at"] >= beijing_day_start:
        raise HTTPException(status_code=409, detail="来源账号必须是前一天以前已确认封禁的账号，当天受限不迁移")
    target = by_id.get(str(payload.target_account_id))
    target_is_healthy = bool(
        target and target["status"] == "connected" and target["is_active"]
        and target["migration_status"] == "active" and target["health_check_status"] == "healthy"
        and target["last_health_check_at"] and target["last_health_check_at"] >= beijing_day_start
        and (not target["last_peer_flood_at"] or target["last_peer_flood_at"] < beijing_day_start)
        and (not target["last_restricted_at"] or target["last_restricted_at"] < beijing_day_start)
    )
    if not target_is_healthy or not 1 <= target["tier"] <= 4:
        raise HTTPException(status_code=409, detail="接管账号必须当天健康检测通过、正常运行且无受限记录")

    image_path = _validated_migration_image_path(payload.image_path)
    if not image_path:
        raise HTTPException(status_code=422, detail="迁移任务必须上传图片，并与文字作为一条图文消息发送")
    if len(payload.intro_message.strip()) > 1024:
        raise HTTPException(status_code=422, detail="图文消息文字不能超过1024个字符")
    campaign_filters = dict(payload.filters)
    campaign_filters["migration_image_path"] = image_path

    campaign = (
        await db.execute(
            text(
                """
                INSERT INTO telegram_user_migration_campaigns
                  (source_account_id, target_account_id, name, intro_message,
                   rate_per_minute, filters, created_by)
                VALUES (CAST(:source AS uuid), CAST(:target AS uuid), :name, :message,
                        :rate, CAST(:filters AS jsonb), CAST(:created_by AS uuid))
                RETURNING id::text
                """
            ),
            {
                "source": str(payload.source_account_id), "target": str(payload.target_account_id),
                "name": payload.name.strip(), "message": payload.intro_message.strip(),
                "rate": payload.rate_per_minute, "filters": __import__("json").dumps(campaign_filters),
                "created_by": _operator_id(operator),
            },
        )
    ).first()
    campaign_id = str(campaign[0])
    inserted = 0
    for user_id in payload.user_ids:
        result = await db.execute(
            text(
                """
                INSERT INTO telegram_user_migration_tasks
                  (campaign_id, user_id, conversation_id, telegram_chat_id,
                   source_account_id, target_account_id, source_access_hash)
                SELECT CAST(:campaign AS uuid), u.id, p.conversation_id, p.chat_id,
                       CAST(:source AS uuid), CAST(:target AS uuid), p.access_hash
                FROM users u
                JOIN LATERAL (
                  SELECT source.conversation_id, source.chat_id, source.access_hash
                  FROM (
                    SELECT p.conversation_id, p.chat_id, p.access_hash,
                           p.last_seen_at, 1 AS priority
                    FROM telegram_peer_cache p
                    WHERE p.account_id=CAST(:source AS uuid) AND p.user_id=u.id
                    UNION ALL
                    SELECT al.conversation_id,
                           CASE WHEN u.external_id ~ '^tg_[0-9]+$'
                                THEN substring(u.external_id FROM 4)::bigint END,
                           NULL::bigint, al.created_at, 2 AS priority
                    FROM attribution_links al
                    WHERE al.sender_account_id=:source
                      AND al.user_id=u.id
                  ) source
                  WHERE source.chat_id IS NOT NULL
                  ORDER BY source.priority, source.last_seen_at DESC LIMIT 1
                ) p ON TRUE
                WHERE u.id=CAST(:user_id AS uuid)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM telegram_user_migration_tasks existing
                    WHERE existing.user_id=u.id
                      AND existing.status NOT IN ('failed','cancelled','unreachable')
                  )
                ON CONFLICT (campaign_id, user_id) DO NOTHING
                RETURNING id
                """
            ),
            {"campaign": campaign_id, "source": str(payload.source_account_id), "target": str(payload.target_account_id), "user_id": str(user_id)},
        )
        inserted += 1 if result.first() else 0
    if inserted == 0:
        await db.rollback()
        raise HTTPException(status_code=409, detail="所选用户没有可创建的迁移任务，可能已在其他迁移批次中")
    await db.commit()
    return {"id": campaign_id, "tasks_created": inserted, "status": "draft"}


@router.get("/campaigns")
async def list_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT c.id::text, c.name, c.status, c.rate_per_minute,
                       c.source_account_id::text, s.display_name AS source_account,
                       c.target_account_id::text, t.display_name AS target_account,
                       c.created_at, c.started_at, c.completed_at,
                       COUNT(mt.id) AS total,
                       COUNT(mt.id) FILTER (WHERE mt.status='success') AS success,
                       COUNT(mt.id) FILTER (WHERE mt.status='sent') AS sent,
                       COUNT(mt.id) FILTER (WHERE mt.status='unreachable') AS unreachable,
                       COUNT(mt.id) FILTER (WHERE mt.status='restricted') AS restricted,
                       COUNT(mt.id) FILTER (WHERE mt.status='retry_wait') AS retry_wait,
                       COUNT(mt.id) FILTER (WHERE mt.status IN ('pending','resolving','resolved','sending')) AS pending
                FROM telegram_user_migration_campaigns c
                JOIN telegram_accounts s ON s.id=c.source_account_id
                JOIN telegram_accounts t ON t.id=c.target_account_id
                LEFT JOIN telegram_user_migration_tasks mt ON mt.campaign_id=c.id
                GROUP BY c.id,s.display_name,t.display_name
                ORDER BY c.created_at DESC LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.get("/campaigns/{campaign_id}/tasks")
async def list_tasks(
    campaign_id: UUID,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT mt.id::text, mt.user_id::text, u.external_id, u.nickname,
                       mt.telegram_chat_id, mt.status, mt.attempt_count,
                       mt.failure_code, mt.failure_reason, mt.next_attempt_at,
                       mt.sent_at, mt.replied_at, mt.video_sequence_reset_at, mt.updated_at
                FROM telegram_user_migration_tasks mt
                JOIN users u ON u.id=mt.user_id
                WHERE mt.campaign_id=CAST(:campaign_id AS uuid)
                  AND (CAST(:status AS text) IS NULL
                       OR mt.status=CAST(:status AS text))
                ORDER BY mt.created_at DESC LIMIT :limit
                """
            ),
            {"campaign_id": str(campaign_id), "status": status, "limit": limit},
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    row = (
        await db.execute(
            text("""
              UPDATE telegram_user_migration_campaigns c
              SET status='running', started_at=COALESCE(started_at,NOW()), updated_at=NOW()
              WHERE c.id=CAST(:id AS uuid) AND c.status IN ('draft','paused')
                AND EXISTS (
                  SELECT 1 FROM video_reinvite_account_state s
                  WHERE s.account_id=c.source_account_id
                    AND s.health_check_status='banned'
                    AND s.paused_at<date_trunc('day',NOW() AT TIME ZONE 'Asia/Shanghai')
                                      AT TIME ZONE 'Asia/Shanghai'
                )
              RETURNING c.id
            """),
            {"id": str(campaign_id)},
        )
    ).first()
    await db.commit()
    if not row:
        raise HTTPException(status_code=409, detail="批次不能启动：来源账号必须是前一天以前已确认封禁的账号")
    return {"ok": True, "status": "running"}


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    await db.execute(
        text("UPDATE telegram_user_migration_campaigns SET status='paused', updated_at=NOW() WHERE id=CAST(:id AS uuid) AND status='running'"),
        {"id": str(campaign_id)},
    )
    await db.commit()
    return {"ok": True, "status": "paused"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    _operator: Any = Depends(require_operator),
):
    result = await db.execute(
        text("UPDATE telegram_user_migration_tasks SET status='retry_wait', next_attempt_at=NOW(), failure_reason=NULL, updated_at=NOW() WHERE id=CAST(:id AS uuid) AND status IN ('failed','unreachable','restricted','retry_wait')"),
        {"id": str(task_id)},
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=409, detail="任务当前状态不能重试")
    return {"ok": True, "status": "retry_wait"}
