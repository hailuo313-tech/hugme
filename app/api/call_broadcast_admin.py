"""Admin API for video call broadcast assets (operator upload to CALL_BROADCAST_VIDEO_ROOT)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import _serialize_row, _telegram_chat_id_from_external, require_operator
from core.config import settings
from core.database import get_db
from services.call_broadcast.incoming_review import (
    _created_at_epoch,
    _remaining_review_seconds,
    accept_operator_review,
    cancel_stale_operator_review,
    hydrate_pending_review_from_job,
    reject_operator_review,
)
from services.call_broadcast.incoming_review_registry import snapshot_pending
from services.call_broadcast.jobs import enqueue_call_broadcast_job, resolve_inbound_call_context
from services.call_broadcast.ffmpeg_pipeline import probe_video_duration_seconds
from services.call_broadcast.duration import stored_asset_duration_seconds
from services.call_broadcast.peers import resolve_account_and_access_hash
from services.call_broadcast.remote_stills import (
    list_job_recording,
    list_job_stills,
    resolve_recording_file,
    resolve_still_file,
)
from services.call_broadcast.worker import spawn_immediate_tick

router = APIRouter()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
REVIEW_ACTION_ERROR_ZH = {
    "review_expired_or_missing": "来电审核已超时，对方可能已挂断。可点「拒绝」清掉这条，或再试一次接听。",
    "job_not_pending": "这条来电已处理或不存在",
    "account_busy_on_call": "该接待号正在通话中，请稍后再接",
    "video_asset_not_found": "所选视频不存在或已下架",
}


def _review_action_error(reason: Any) -> str:
    key = str(reason or "accept_failed")
    return REVIEW_ACTION_ERROR_ZH.get(key, key)


def _video_broadcast_dir() -> Path:
    root = Path(getattr(settings, "CALL_BROADCAST_VIDEO_ROOT", "/data/videos"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field_name}") from exc


def _safe_video_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise HTTPException(status_code=422, detail=f"unsupported video type; allowed: {allowed}")
    return suffix


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    data = row._mapping if hasattr(row, "_mapping") else row
    return dict(data)


def _serialize_asset(row: Any) -> dict[str, Any]:
    item = _row_mapping(row)
    for key in ("id",):
        if item.get(key) is not None:
            item[key] = str(item[key])
    for key in ("created_at", "updated_at"):
        if item.get(key) is not None:
            item[key] = item[key].isoformat()
    item["preview_url"] = f"/api/v1/call-broadcast/admin/video-assets/{item.get('id')}/file"
    return item


class VideoAssetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    duration_seconds: int | None = Field(default=None, ge=5, le=600)
    status: str | None = Field(default=None, pattern="^(active|archived)$")
    play_sequence: int | None = Field(default=None, ge=1, le=3)


def _validate_play_sequence(value: int | None) -> int | None:
    if value is None:
        return None
    seq = int(value)
    if seq not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="play_sequence must be 1, 2, or 3")
    return seq


class ManualCallTarget(BaseModel):
    user_id: str
    conversation_id: str


class ManualCallRequest(BaseModel):
    video_asset_id: str
    targets: list[ManualCallTarget] = Field(min_length=1, max_length=20)


class IncomingReviewAcceptRequest(BaseModel):
    video_asset_id: str


def _serialize_chat_user(row: Any) -> dict[str, Any]:
    item = _serialize_row(row)
    external_id = item.get("external_id")
    item["chat_id"] = _telegram_chat_id_from_external(
        str(external_id) if external_id is not None else None
    )
    return item


def _serialize_call_history_user(row: Any) -> dict[str, Any]:
    item = _serialize_row(row)
    external_id = item.get("external_id")
    chat_id = item.get("chat_id")
    if chat_id is None:
        item["chat_id"] = _telegram_chat_id_from_external(
            str(external_id) if external_id is not None else None
        )
    if item.get("user_id") is not None:
        item["user_id"] = str(item["user_id"])
    if item.get("conversation_id") is not None:
        item["conversation_id"] = str(item["conversation_id"])
    for key in ("last_call_at",):
        if item.get(key) is not None and hasattr(item[key], "isoformat"):
            item[key] = item[key].isoformat()
    return item


def _serialize_call_history_record(row: Any) -> dict[str, Any]:
    item = _serialize_row(row)
    if item.get("job_id") is not None:
        item["job_id"] = str(item["job_id"])
    if item.get("user_id") is not None:
        item["user_id"] = str(item["user_id"])
    for key in ("started_at", "ended_at", "call_at"):
        if item.get(key) is not None and hasattr(item[key], "isoformat"):
            item[key] = item[key].isoformat()
    if item.get("duration_seconds") is not None:
        item["duration_seconds"] = int(item["duration_seconds"])
    if item.get("inbound_call_number") is not None:
        item["inbound_call_number"] = int(item["inbound_call_number"])
    if item.get("telegram_account_id") is not None:
        item["telegram_account_id"] = str(item["telegram_account_id"])
    item.pop("total_count", None)
    job_id = item.get("job_id")
    item["stills"] = list_job_stills(str(job_id)) if job_id else []
    item["recording"] = list_job_recording(str(job_id)) if job_id else None
    return item


_CALL_HISTORY_FROM_SQL = """
    FROM call_broadcast_jobs j
    LEFT JOIN video_broadcast_assets v ON v.id = j.video_asset_id
    LEFT JOIN telegram_accounts ta ON ta.id = j.account_id
    LEFT JOIN users u_by_id
        ON j.user_id ~* '^[0-9a-f-]{36}$'
       AND u_by_id.id::text = j.user_id
    LEFT JOIN users u_by_ext
        ON u_by_ext.external_id = COALESCE(
            NULLIF(j.external_user_id, ''),
            'tg_' || j.chat_id::text
        )
"""

_CALL_HISTORY_SELECT_SQL = """
    SELECT
        j.id::text AS job_id,
        COALESCE(u_by_id.id::text, u_by_ext.id::text, NULLIF(j.user_id, '')) AS user_id,
        COALESCE(u_by_id.nickname, u_by_ext.nickname) AS nickname,
        COALESCE(
            u_by_ext.external_id,
            u_by_id.external_id,
            j.external_user_id,
            'tg_' || j.chat_id::text
        ) AS external_id,
        j.chat_id,
        j.status,
        j.failure_reason,
        j.trigger_source,
        j.started_at,
        j.ended_at,
        COALESCE(j.ended_at, j.started_at, j.created_at) AS call_at,
        v.title AS video_title,
        CASE
            WHEN j.status IN ('completed', 'cancelled', 'failed') THEN
                GREATEST(
                    1,
                    COALESCE(
                        NULLIF((j.metadata->>'playback_seconds')::int, 0),
                        NULLIF((j.metadata->>'stream_wall_seconds')::int, 0),
                        LEAST(
                            NULLIF(EXTRACT(EPOCH FROM (j.ended_at - j.started_at))::int, 0),
                            COALESCE(v.duration_seconds, 30) + 15
                        ),
                        v.duration_seconds,
                        30
                    )
                )::int
            ELSE 0
        END AS duration_seconds,
        COALESCE(
            NULLIF((j.metadata->>'call_attempt_number')::int, 0),
            NULLIF((j.metadata->>'inbound_call_number')::int, 0),
            NULLIF((j.metadata->>'play_sequence')::int, 0)
        ) AS inbound_call_number,
        j.account_id::text AS telegram_account_id,
        ta.phone AS telegram_account_phone,
        ta.display_name AS telegram_account_name,
        ta.username AS telegram_account_username,
        COALESCE(ta.metadata->>'reply_mode', 'ai') AS telegram_account_reply_mode,
        COALESCE(
            NULLIF(ta.display_name, ''),
            CASE
                WHEN ta.username IS NOT NULL AND ta.username <> ''
                THEN '@' || ta.username
            END,
            NULLIF(ta.phone, '')
        ) AS telegram_account_label,
        u_by_id.external_id AS user_external_id,
        j.external_user_id
"""


def _call_history_filter_sql(
    *,
    search: str | None,
    reply_mode: str | None,
) -> tuple[str, dict[str, Any]]:
    search_like = f"%{search.strip()}%" if search and search.strip() else None
    normalized_reply_mode = None
    if reply_mode and reply_mode.strip():
        normalized_reply_mode = reply_mode.strip().lower()
        if normalized_reply_mode not in {"ai", "fixed"}:
            raise HTTPException(status_code=422, detail="reply_mode must be ai or fixed")
    params: dict[str, Any] = {
        "search": search_like,
        "reply_mode": normalized_reply_mode,
    }
    where = """
        AND (
            CAST(:reply_mode AS TEXT) IS NULL
            OR COALESCE(ta.metadata->>'reply_mode', 'ai') = :reply_mode
        )
        AND (
            CAST(:search AS TEXT) IS NULL
            OR COALESCE(u_by_id.nickname, u_by_ext.nickname) ILIKE :search
            OR u_by_id.external_id ILIKE :search
            OR u_by_ext.external_id ILIKE :search
            OR j.external_user_id ILIKE :search
            OR ('tg_' || j.chat_id::text) ILIKE :search
            OR j.chat_id::text ILIKE :search
            OR v.title ILIKE :search
            OR ta.phone ILIKE :search
            OR ta.display_name ILIKE :search
            OR ta.username ILIKE :search
            OR COALESCE(
                NULLIF(ta.display_name, ''),
                CASE
                    WHEN ta.username IS NOT NULL AND ta.username <> ''
                    THEN '@' || ta.username
                END,
                NULLIF(ta.phone, '')
            ) ILIKE :search
        )
    """
    return where, params


# Legacy alias kept for ad-hoc diagnostics scripts.
_CALL_HISTORY_RECORDS_SQL = f"""
    {_CALL_HISTORY_SELECT_SQL}
    {_CALL_HISTORY_FROM_SQL}
    WHERE 1 = 1
"""


_CALL_HISTORY_BASE_SQL = """
    WITH completed_calls AS (
        SELECT
            j.user_id,
            j.external_user_id,
            j.chat_id,
            j.conversation_id,
            j.trigger_source,
            j.ended_at,
            v.title AS video_title,
            u.id AS resolved_user_id,
            u.nickname,
            u.external_id AS user_external_id
        FROM call_broadcast_jobs j
        LEFT JOIN video_broadcast_assets v ON v.id = j.video_asset_id
        LEFT JOIN users u ON (
            (j.user_id ~* '^[0-9a-f-]{36}$' AND u.id::text = j.user_id)
            OR (j.external_user_id IS NOT NULL AND u.external_id = j.external_user_id)
            OR (u.external_id = 'tg_' || j.chat_id::text)
        )
        WHERE j.status = 'completed'
    ),
    keyed AS (
        SELECT
            *,
            COALESCE(
                resolved_user_id::text,
                NULLIF(user_id, ''),
                external_user_id,
                'chat:' || chat_id::text
            ) AS group_key
        FROM completed_calls
    ),
    grouped AS (
        SELECT
            group_key,
            COALESCE(MAX(resolved_user_id::text), MAX(NULLIF(user_id, ''))) AS user_id,
            MAX(nickname) AS nickname,
            COALESCE(
                MAX(user_external_id),
                MAX(external_user_id),
                'tg_' || MAX(chat_id)::text
            ) AS external_id,
            MAX(chat_id) AS chat_id,
            MAX(conversation_id::text) AS conversation_id,
            COUNT(*)::int AS call_count,
            MAX(ended_at) AS last_call_at,
            (array_agg(trigger_source ORDER BY ended_at DESC NULLS LAST))[1] AS last_trigger_source,
            (array_agg(video_title ORDER BY ended_at DESC NULLS LAST))[1] AS last_video_title
        FROM keyed
        GROUP BY group_key
    )
"""


def _serialize_incoming_review(row: Any, live: dict[str, Any] | None = None) -> dict[str, Any]:
    item = _serialize_row(row)
    if item.get("id") is not None:
        item["id"] = str(item["id"])
    if item.get("account_id") is not None:
        item["account_id"] = str(item["account_id"])
    if item.get("created_at") is not None and hasattr(item["created_at"], "isoformat"):
        item["created_at"] = item["created_at"].isoformat()
    metadata = item.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    if isinstance(metadata, dict):
        item["call_number"] = metadata.get("call_number")
        item["inbound_call_number"] = metadata.get("inbound_call_number")
        item["call_attempt_number"] = metadata.get("call_attempt_number")
        item["completed_calls"] = metadata.get("completed_calls")
        item["completed_inbound_calls"] = metadata.get("completed_inbound_calls")
        item["matched_keyword"] = metadata.get("matched_keyword")
    if item.get("trigger_source") is not None:
        item["trigger_source"] = str(item["trigger_source"])
    if live:
        item["seconds_remaining"] = live.get("seconds_remaining")
        if live.get("inbound_call_number") is not None:
            item["inbound_call_number"] = int(live["inbound_call_number"])
    return item


async def _enrich_incoming_review_call_counts(
    db: AsyncSession,
    item: dict[str, Any],
) -> dict[str, Any]:
    chat_id = item.get("chat_id")
    if chat_id is None:
        return item
    call_ctx = await resolve_inbound_call_context(db, int(chat_id))
    completed_inbound_calls = int(call_ctx.get("completed_inbound_calls") or 0)
    inbound_call_number = int(call_ctx.get("inbound_call_number") or (completed_inbound_calls + 1))
    item["completed_inbound_calls"] = completed_inbound_calls
    item["inbound_call_number"] = inbound_call_number
    item["call_attempt_number"] = int(
        call_ctx.get("call_attempt_number") or call_ctx.get("prior_inbound_attempts", 0) + 1
    )
    item["completed_calls"] = int(call_ctx.get("completed_calls") or completed_inbound_calls)
    item["call_number"] = int(call_ctx.get("call_number") or item["call_attempt_number"])
    return item


@router.get("/incoming-reviews")
async def list_incoming_call_reviews(
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    """Pending inbound calls (4th+) waiting for operator accept/reject."""
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    j.id,
                    j.chat_id,
                    j.account_id,
                    j.trace_id,
                    j.metadata,
                    j.trigger_source,
                    j.created_at,
                    u.nickname,
                    u.external_id
                FROM call_broadcast_jobs j
                LEFT JOIN users u ON u.external_id = 'tg_' || j.chat_id::text
                WHERE j.status = 'pending_operator'
                ORDER BY j.created_at ASC
                LIMIT 50
                """
            )
        )
    ).fetchall()
    live_rows: list[Any] = []
    zombie_after = max(
        int(getattr(settings, "CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS", 90)) * 2,
        300,
    )
    for row in rows:
        mapping = dict(row._mapping)
        trigger_source = str(mapping.get("trigger_source") or "")
        created_epoch = _created_at_epoch(mapping.get("created_at"))
        age_seconds = time.time() - created_epoch if created_epoch is not None else 0
        if trigger_source != "inbound_keyword_review" and age_seconds >= zombie_after:
            await cancel_stale_operator_review(str(mapping.get("id")))
            continue
        await hydrate_pending_review_from_job(
            db,
            str(mapping.get("id")),
            allow_expired=age_seconds
            > int(getattr(settings, "CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS", 90)),
        )
        live_rows.append(row)
    live_by_job = {item["job_id"]: item for item in snapshot_pending()}
    items: list[dict[str, Any]] = []
    for row in live_rows:
        mapping = dict(row._mapping)
        serialized = _serialize_incoming_review(
            row,
            live_by_job.get(str(mapping.get("id"))),
        )
        trigger_source = str(mapping.get("trigger_source") or "")
        remaining = _remaining_review_seconds(
            trigger_source=trigger_source,
            created_at=mapping.get("created_at"),
        )
        if serialized.get("seconds_remaining") is None:
            serialized["seconds_remaining"] = remaining
        serialized["expired"] = (
            trigger_source != "inbound_keyword_review" and remaining <= 0
        )
        items.append(await _enrich_incoming_review_call_counts(db, serialized))
    logger.bind(
        operator_id=operator.get("sub"),
        pending=len(items),
    ).info("call_broadcast.admin.incoming_reviews.list")
    return {"items": items, "total": len(items)}


@router.post("/incoming-reviews/{job_id}/accept", status_code=status.HTTP_202_ACCEPTED)
async def accept_incoming_call_review(
    job_id: str,
    payload: IncomingReviewAcceptRequest,
    operator: dict = Depends(require_operator),
):
    jid = _validate_uuid(job_id, "job_id")
    vid = _validate_uuid(payload.video_asset_id, "video_asset_id")
    result = await accept_operator_review(
        job_id=jid,
        video_asset_id=vid,
        operator_id=str(operator.get("sub") or ""),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409,
            detail=_review_action_error(result.get("reason") or "accept_failed"),
        )
    return result


@router.post("/incoming-reviews/{job_id}/reject", status_code=status.HTTP_202_ACCEPTED)
async def reject_incoming_call_review(
    job_id: str,
    operator: dict = Depends(require_operator),
):
    jid = _validate_uuid(job_id, "job_id")
    result = await reject_operator_review(
        job_id=jid,
        operator_id=str(operator.get("sub") or ""),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409,
            detail=_review_action_error(result.get("reason") or "reject_failed"),
        )
    return result


@router.get("/video-assets")
async def list_video_broadcast_assets(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT id, title, file_path, duration_seconds, ffmpeg_profile,
                       play_sequence, status, metadata, created_at, updated_at
                FROM video_broadcast_assets
                WHERE (:include_archived OR status = 'active')
                ORDER BY play_sequence ASC NULLS LAST, created_at DESC
                LIMIT 200
                """
            ),
            {"include_archived": include_archived},
        )
    ).fetchall()
    return {"items": [_serialize_asset(row) for row in rows]}


@router.post("/video-assets", status_code=status.HTTP_201_CREATED)
async def upload_video_broadcast_asset(
    title: str = Form(...),
    duration_seconds: int | None = Form(default=None),
    play_sequence: int = Form(..., description="1=first inbound call, 2=second, 3=third"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    clean_title = str(title or "").strip()
    if not clean_title:
        raise HTTPException(status_code=422, detail="title is required")
    sequence = _validate_play_sequence(play_sequence)
    if sequence is None:
        raise HTTPException(status_code=422, detail="play_sequence is required (1, 2, or 3)")

    suffix = _safe_video_suffix(file.filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 100MB)")

    asset_id = str(uuid.uuid4())
    filename = f"{asset_id}{suffix}"
    target = _video_broadcast_dir() / filename
    target.write_bytes(content)

    probed = await probe_video_duration_seconds(str(target))
    duration = stored_asset_duration_seconds(
        probed_seconds=probed,
        configured_seconds=duration_seconds,
        default_seconds=int(getattr(settings, "CALL_BROADCAST_DEFAULT_DURATION_SECONDS", 30)),
    )

    await db.execute(
        text(
            """
            UPDATE video_broadcast_assets
            SET status = 'archived', updated_at = NOW()
            WHERE status = 'active' AND play_sequence = :play_sequence
            """
        ),
        {"play_sequence": sequence},
    )

    row = (
        await db.execute(
            text(
                """
                INSERT INTO video_broadcast_assets (
                    id, title, file_path, duration_seconds, play_sequence, status, metadata
                ) VALUES (
                    CAST(:id AS uuid), :title, :file_path, :duration_seconds, :play_sequence,
                    'active', CAST(:metadata AS jsonb)
                )
                RETURNING id, title, file_path, duration_seconds, ffmpeg_profile, play_sequence,
                          status, metadata, created_at, updated_at
                """
            ),
            {
                "id": asset_id,
                "title": clean_title,
                "file_path": str(target),
                "duration_seconds": duration,
                "play_sequence": sequence,
                "metadata": f'{{"source":"admin_upload","play_sequence":{sequence}}}',
            },
        )
    ).fetchone()
    await db.commit()
    return _serialize_asset(row)


@router.get("/video-assets/{asset_id}/file")
async def download_video_broadcast_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    aid = _validate_uuid(asset_id, "asset_id")
    row = (
        await db.execute(
            text(
                """
                SELECT file_path, title
                FROM video_broadcast_assets
                WHERE id = CAST(:id AS uuid)
                LIMIT 1
                """
            ),
            {"id": aid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video asset not found")

    mapping = _row_mapping(row)
    path = Path(str(mapping.get("file_path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="video file missing on disk")

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name,
    )


@router.patch("/video-assets/{asset_id}")
async def update_video_broadcast_asset(
    asset_id: str,
    payload: VideoAssetUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    aid = _validate_uuid(asset_id, "asset_id")
    assignments: list[str] = []
    values: dict[str, Any] = {"id": aid}
    if payload.title is not None:
        values["title"] = payload.title.strip()
        assignments.append("title = :title")
    if payload.duration_seconds is not None:
        values["duration_seconds"] = int(payload.duration_seconds)
        assignments.append("duration_seconds = :duration_seconds")
    if payload.status is not None:
        values["status"] = payload.status
        assignments.append("status = :status")
    if payload.play_sequence is not None:
        values["play_sequence"] = _validate_play_sequence(payload.play_sequence)
        assignments.append("play_sequence = :play_sequence")
    if not assignments:
        raise HTTPException(status_code=422, detail="no fields to update")

    if payload.play_sequence is not None and payload.status != "archived":
        await db.execute(
            text(
                """
                UPDATE video_broadcast_assets
                SET status = 'archived', updated_at = NOW()
                WHERE status = 'active'
                  AND play_sequence = :play_sequence
                  AND id <> CAST(:id AS uuid)
                """
            ),
            {"play_sequence": values["play_sequence"], "id": aid},
        )

    assignments.append("updated_at = NOW()")
    row = (
        await db.execute(
            text(
                f"""
                UPDATE video_broadcast_assets
                SET {", ".join(assignments)}
                WHERE id = CAST(:id AS uuid)
                RETURNING id, title, file_path, duration_seconds, ffmpeg_profile, play_sequence,
                          status, metadata, created_at, updated_at
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video asset not found")
    await db.commit()
    return _serialize_asset(row)


@router.get("/call-history")
async def list_call_broadcast_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, description="nickname / external_id / chat_id"),
    reply_mode: str | None = Query(None, description="telegram account reply mode: ai or fixed"),
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    """Each completed video call with per-call duration."""
    await db.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
    where, params = _call_history_filter_sql(search=search, reply_mode=reply_mode)
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    total_row = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*)
                {_CALL_HISTORY_FROM_SQL}
                WHERE 1 = 1
                {where}
                """
            ),
            params,
        )
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    rows = (
        await db.execute(
            text(
                f"""
                {_CALL_HISTORY_SELECT_SQL}
                {_CALL_HISTORY_FROM_SQL}
                WHERE 1 = 1
                {where}
                ORDER BY call_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    items = [_serialize_call_history_record(row) for row in rows]
    logger.bind(
        operator_id=operator.get("sub"),
        page=page,
        page_size=page_size,
        total=total,
        returned=len(items),
    ).info("call_broadcast.admin.call_history.list")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/call-history/{job_id}/stills/{index}")
async def download_call_history_still(
    job_id: str,
    index: int,
    _operator: dict = Depends(require_operator),
):
    """Serve one remote-party JPEG captured during auto-play."""
    _validate_uuid(job_id, "job_id")
    if index < 0 or index > 999:
        raise HTTPException(status_code=404, detail="still not found")
    path = resolve_still_file(job_id, index)
    if path is None:
        raise HTTPException(status_code=404, detail="still not found")
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=path.name,
    )


@router.get("/call-history/{job_id}/recording")
async def download_call_history_recording(
    job_id: str,
    _operator: dict = Depends(require_operator),
):
    """Serve the remote-party MP4 captured during auto-play."""
    _validate_uuid(job_id, "job_id")
    path = resolve_recording_file(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{job_id}-remote.mp4",
    )


@router.get("/call-history-users")
async def list_call_broadcast_history_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, description="nickname / external_id / chat_id"),
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    """Users who have completed at least one video call broadcast."""
    await db.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
    search_like = f"%{search.strip()}%" if search and search.strip() else None
    params: dict[str, Any] = {
        "search": search_like,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    where = """
        WHERE (
            CAST(:search AS TEXT) IS NULL
            OR grouped.nickname ILIKE :search
            OR grouped.external_id ILIKE :search
            OR grouped.group_key ILIKE :search
            OR grouped.chat_id::text ILIKE :search
        )
    """
    total_row = (
        await db.execute(
            text(
                f"""
                {_CALL_HISTORY_BASE_SQL}
                SELECT COUNT(*) FROM grouped
                {where}
                """
            ),
            params,
        )
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    rows = (
        await db.execute(
            text(
                f"""
                {_CALL_HISTORY_BASE_SQL}
                SELECT
                    grouped.user_id,
                    grouped.nickname,
                    grouped.external_id,
                    grouped.chat_id,
                    grouped.conversation_id,
                    grouped.call_count,
                    grouped.last_call_at,
                    grouped.last_trigger_source,
                    grouped.last_video_title
                FROM grouped
                {where}
                ORDER BY grouped.last_call_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    items = [_serialize_call_history_user(row) for row in rows]
    logger.bind(
        operator_id=operator.get("sub"),
        page=page,
        page_size=page_size,
        total=total,
        returned=len(items),
    ).info("call_broadcast.admin.call_history_users.list")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/chat-users")
async def list_call_broadcast_chat_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, description="nickname / external_id ILIKE"),
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    """List Telegram chat users eligible for manual video call broadcast."""
    await db.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
    search_like = f"%{search.strip()}%" if search and search.strip() else None
    params: dict[str, Any] = {
        "search": search_like,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    where = """
        WHERE c.channel IN ('telegram', 'telegram_real_user')
          AND u.external_id LIKE 'tg_%'
          AND (CAST(:search AS TEXT) IS NULL
               OR u.nickname ILIKE :search
               OR u.external_id ILIKE :search)
    """
    total_row = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT u.id)
                FROM users u
                JOIN conversations c ON c.user_id = u.id
                {where}
                """
            ),
            params,
        )
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    rows = (
        await db.execute(
            text(
                f"""
                SELECT *
                FROM (
                  SELECT DISTINCT ON (u.id)
                    u.id AS user_id,
                    u.nickname,
                    u.external_id,
                    u.status AS user_status,
                    c.id AS conversation_id,
                    c.channel,
                    c.state AS conversation_state,
                    c.last_message_at,
                    (
                      SELECT m.sender_id
                      FROM messages m
                      JOIN telegram_accounts ta ON ta.id::text = m.sender_id
                      WHERE m.conversation_id = c.id
                        AND m.sender_type = 'assistant'
                      ORDER BY m.created_at DESC
                      LIMIT 1
                    ) AS telegram_account_id
                  FROM users u
                  JOIN conversations c ON c.user_id = u.id
                  {where}
                  ORDER BY u.id, c.last_message_at DESC NULLS LAST
                ) chat_users
                ORDER BY chat_users.last_message_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    items = [_serialize_chat_user(row) for row in rows]
    logger.bind(
        operator_id=operator.get("sub"),
        page=page,
        page_size=page_size,
        total=total,
        returned=len(items),
    ).info("call_broadcast.admin.chat_users.list")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/manual-calls", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_manual_call_broadcast(
    payload: ManualCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    """Operator-initiated video calls for selected chat users."""
    if not getattr(settings, "CALL_BROADCAST_ENABLED", False):
        raise HTTPException(
            status_code=503,
            detail="CALL_BROADCAST_ENABLED is off; enable before manual video calls",
        )

    video_asset_id = _validate_uuid(payload.video_asset_id, "video_asset_id")
    asset_row = (
        await db.execute(
            text(
                """
                SELECT id, title, status
                FROM video_broadcast_assets
                WHERE id = CAST(:id AS uuid) AND status = 'active'
                LIMIT 1
                """
            ),
            {"id": video_asset_id},
        )
    ).fetchone()
    if asset_row is None:
        raise HTTPException(status_code=404, detail="active video asset not found")

    trace_id = getattr(request.state, "trace_id", None) or f"admin-manual-{uuid.uuid4().hex[:12]}"
    operator_id = str(operator.get("sub") or "")
    inserted = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for target in payload.targets:
        try:
            uid = _validate_uuid(target.user_id, "user_id")
            cid = _validate_uuid(target.conversation_id, "conversation_id")
        except HTTPException as exc:
            errors.append({"user_id": target.user_id, "reason": str(exc.detail)})
            skipped += 1
            continue

        row = (
            await db.execute(
                text(
                    """
                    SELECT
                      u.id AS user_id,
                      u.external_id,
                      c.id AS conversation_id,
                      c.channel,
                      (
                        SELECT m.sender_id
                        FROM messages m
                        JOIN telegram_accounts ta ON ta.id::text = m.sender_id
                        WHERE m.conversation_id = c.id
                          AND m.sender_type = 'assistant'
                        ORDER BY m.created_at DESC
                        LIMIT 1
                      ) AS telegram_account_id
                    FROM conversations c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.id = CAST(:cid AS uuid)
                      AND u.id = CAST(:uid AS uuid)
                    LIMIT 1
                    """
                ),
                {"cid": cid, "uid": uid},
            )
        ).fetchone()
        if row is None:
            errors.append({"user_id": uid, "reason": "conversation not found for user"})
            skipped += 1
            continue

        mapping = dict(row._mapping)
        channel = mapping.get("channel")
        if channel not in ("telegram", "telegram_real_user"):
            errors.append({"user_id": uid, "reason": f"unsupported channel={channel}"})
            skipped += 1
            continue

        chat_id = _telegram_chat_id_from_external(
            str(mapping.get("external_id") or "")
        )
        if chat_id is None:
            errors.append({"user_id": uid, "reason": "cannot resolve telegram chat_id"})
            skipped += 1
            continue

        preferred_account_id = (
            str(mapping.get("telegram_account_id"))
            if mapping.get("telegram_account_id") is not None
            else None
        )
        account_id, access_hash = await resolve_account_and_access_hash(
            chat_id=int(chat_id),
            preferred_account_id=preferred_account_id,
        )
        if not account_id or not access_hash:
            errors.append(
                {
                    "user_id": uid,
                    "reason": "cannot resolve telegram peer on any active account",
                }
            )
            skipped += 1
            continue

        try:
            count = await enqueue_call_broadcast_job(
                db,
                user_id=uid,
                external_user_id=str(mapping.get("external_id") or ""),
                conversation_id=cid,
                chat_id=int(chat_id),
                account_id=account_id,
                trigger_source="admin_manual",
                matched_keyword="admin_manual",
                trace_id=trace_id,
                video_asset_id=video_asset_id,
                metadata={
                    "operator_id": operator_id,
                    "video_asset_id": video_asset_id,
                    "video_title": str(dict(asset_row._mapping).get("title") or ""),
                    "telegram_access_hash": access_hash,
                },
            )
            if count:
                inserted += 1
            else:
                skipped += 1
                errors.append({"user_id": uid, "reason": "duplicate job skipped"})
        except Exception as exc:
            skipped += 1
            errors.append({"user_id": uid, "reason": type(exc).__name__})

    await db.commit()
    if inserted:
        spawn_immediate_tick(trace_id=trace_id)

    logger.bind(
        operator_id=operator_id,
        trace_id=trace_id,
        video_asset_id=video_asset_id,
        inserted=inserted,
        skipped=skipped,
    ).info("call_broadcast.admin.manual_calls")

    return {
        "status": "accepted",
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "video_asset_id": video_asset_id,
    }


@router.delete("/video-assets/{asset_id}")
async def archive_video_broadcast_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    aid = _validate_uuid(asset_id, "asset_id")
    row = (
        await db.execute(
            text(
                """
                UPDATE video_broadcast_assets
                SET status = 'archived', updated_at = NOW()
                WHERE id = CAST(:id AS uuid) AND status = 'active'
                RETURNING id
                """
            ),
            {"id": aid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="video asset not found")
    await db.commit()
    return {"status": "archived", "id": aid}
