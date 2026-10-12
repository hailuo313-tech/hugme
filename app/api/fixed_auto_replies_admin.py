from __future__ import annotations

import mimetypes
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Date, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.config import settings
from core.database import get_db
from core.redis import get_redis
from services.fixed_auto_reply_service import ensure_schema, run_fixed_auto_reply_tick
from services.fixed_auto_replies_overview import (
    fetch_overview_accounts,
    fetch_overview_failures,
    fetch_overview_rules,
    fetch_overview_summary,
)


router = APIRouter()

ALLOWED_ASSET_TYPES = {"image", "video", "voice", "audio"}
ASSET_DIR_NAME = "fixed-auto-replies"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
OVERVIEW_CACHE_TTL_SECONDS = 300
OVERVIEW_DETAILS_CACHE_TTL_SECONDS = 600


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text_content: str = ""
    delay_seconds: int = Field(default=0, ge=0, le=604800)
    is_active: bool = False
    sort_order: int = 0


class RulePatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    text_content: str | None = None
    delay_seconds: int | None = Field(default=None, ge=0, le=604800)
    is_active: bool | None = None
    sort_order: int | None = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping if hasattr(row, "_mapping") else row)
    for key, value in list(data.items()):
        if isinstance(value, uuid.UUID):
            data[key] = str(value)
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


def _overview_cache_key(range_key: str, target_date: date | None) -> str:
    period_key = target_date.isoformat() if target_date else range_key
    return f"fixed-auto-replies:admin-overview:v4:{period_key}"


def _overview_part_cache_key(part: str, range_key: str, target_date: date | None) -> str:
    period_key = target_date.isoformat() if target_date else range_key
    return f"fixed-auto-replies:overview:{part}:v1:{period_key}"


def _validate_overview_range(range_key: str, target_date: date | None) -> None:
    allowed_ranges = {"today", "yesterday", "week", "month"}
    if target_date is None and range_key not in allowed_ranges:
        raise HTTPException(status_code=400, detail="invalid overview range")


def _overview_query_params(range_key: str, target_date: date | None) -> dict[str, Any]:
    return {"range_key": range_key, "target_date": target_date}


async def _get_cached_part(cache_key: str) -> dict[str, Any] | None:
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        return json.loads(cached) if cached else None
    except Exception:
        return None


async def _set_cached_part(cache_key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
    try:
        redis = await get_redis()
        await redis.setex(
            cache_key,
            ttl_seconds,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception:
        return


async def _get_cached_overview(cache_key: str) -> dict[str, Any] | None:
    return await _get_cached_part(cache_key)


async def _set_cached_overview(cache_key: str, payload: dict[str, Any]) -> None:
    await _set_cached_part(cache_key, payload, ttl_seconds=OVERVIEW_CACHE_TTL_SECONDS)


async def _next_rule_sort_order(db: AsyncSession) -> int:
    row = await db.execute(
        text("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM fixed_auto_reply_rules")
    )
    return int(row.scalar() or 1)


@router.get("/rules")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    rows = await db.execute(
        text(
            """
            SELECT
                r.*,
                COALESCE(a.assets, '[]'::json) AS assets
            FROM fixed_auto_reply_rules r
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_build_object(
                        'id', id,
                        'asset_type', asset_type,
                        'asset_url', asset_url,
                        'storage_path', storage_path,
                        'original_filename', original_filename,
                        'mime_type', mime_type,
                        'file_size_bytes', file_size_bytes,
                        'caption', caption,
                        'sort_order', sort_order,
                        'created_at', created_at
                    )
                    ORDER BY sort_order ASC, created_at ASC
                ) AS assets
                FROM fixed_auto_reply_assets a
                WHERE a.rule_id = r.id
            ) a ON TRUE
            ORDER BY r.sort_order ASC, r.created_at ASC, r.id ASC
            """
        )
    )
    items = []
    for row in rows.fetchall():
        item = _row_to_dict(row)
        if isinstance(item.get("assets"), str):
            try:
                item["assets"] = json.loads(item["assets"])
            except json.JSONDecodeError:
                item["assets"] = []
        item["assets"] = item.get("assets") or []
        items.append(item)
    return {"items": items}


@router.post("/rules")
async def create_rule(
    payload: RulePayload,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    rule_id = str(uuid.uuid4())
    sort_order = await _next_rule_sort_order(db)
    await db.execute(
        text(
            """
            INSERT INTO fixed_auto_reply_rules (
                id, name, text_content, delay_seconds, is_active, activated_at, sort_order
            )
            VALUES (
                :id, :name, :text_content, :delay_seconds, :is_active,
                CASE WHEN :is_active THEN NOW() ELSE NULL END,
                :sort_order
            )
            """
        ),
        {
            "id": rule_id,
            "name": payload.name.strip(),
            "text_content": payload.text_content,
            "delay_seconds": payload.delay_seconds,
            "is_active": payload.is_active,
            "sort_order": sort_order,
        },
    )
    await db.commit()
    return {"id": rule_id, "sort_order": sort_order}


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    payload: RulePatchPayload,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    current = await db.execute(
        text("SELECT is_active FROM fixed_auto_reply_rules WHERE id = :id"),
        {"id": str(rule_id)},
    )
    row = current.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="rule_not_found")

    values = payload.model_dump(exclude_unset=True)
    if not values:
        return {"ok": True}

    params: dict[str, Any] = {"id": str(rule_id)}
    assignments = ["updated_at = NOW()"]
    for key, value in values.items():
        if key == "name" and value is not None:
            value = value.strip()
        assignments.append(f"{key} = :{key}")
        params[key] = value

    if payload.is_active is True and row["is_active"] is not True:
        assignments.append("activated_at = NOW()")

    await db.execute(
        text(f"UPDATE fixed_auto_reply_rules SET {', '.join(assignments)} WHERE id = :id"),
        params,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    await db.execute(text("DELETE FROM fixed_auto_reply_rules WHERE id = :id"), {"id": str(rule_id)})
    await db.commit()
    return {"ok": True}


@router.post("/rules/{rule_id}/assets")
async def upload_asset(
    rule_id: uuid.UUID,
    asset_type: str = Form(...),
    caption: str = Form(""),
    sort_order: int = Form(0),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    asset_type = asset_type.lower().strip()
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="invalid_asset_type")

    exists = await db.execute(
        text("SELECT 1 FROM fixed_auto_reply_rules WHERE id = :id"),
        {"id": str(rule_id)},
    )
    if not exists.scalar():
        raise HTTPException(status_code=404, detail="rule_not_found")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    if not raw:
        raise HTTPException(status_code=400, detail="empty_file")

    original = file.filename or "upload"
    suffix = Path(original).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(file.content_type or "") or ".bin"
    upload_dir = Path(settings.MEDIA_UPLOAD_DIR) / ASSET_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    storage_path = upload_dir / filename
    storage_path.write_bytes(raw)
    asset_url = f"{settings.MEDIA_PUBLIC_PATH.rstrip('/')}/{ASSET_DIR_NAME}/{filename}"

    asset_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO fixed_auto_reply_assets (
                id,
                rule_id,
                asset_type,
                asset_url,
                storage_path,
                original_filename,
                mime_type,
                file_size_bytes,
                caption,
                sort_order
            )
            VALUES (
                :id,
                :rule_id,
                :asset_type,
                :asset_url,
                :storage_path,
                :original_filename,
                :mime_type,
                :file_size_bytes,
                :caption,
                :sort_order
            )
            """
        ),
        {
            "id": asset_id,
            "rule_id": str(rule_id),
            "asset_type": asset_type,
            "asset_url": asset_url,
            "storage_path": str(storage_path),
            "original_filename": original,
            "mime_type": file.content_type,
            "file_size_bytes": len(raw),
            "caption": caption,
            "sort_order": sort_order,
        },
    )
    await db.commit()
    return {"id": asset_id, "asset_url": asset_url}


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    await db.execute(text("DELETE FROM fixed_auto_reply_assets WHERE id = :id"), {"id": str(asset_id)})
    await db.commit()
    return {"ok": True}


@router.get("/jobs")
async def list_jobs(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    limit = max(1, min(limit, 500))
    rows = await db.execute(
        text(
            """
            SELECT
                j.id,
                j.rule_id,
                r.name AS rule_name,
                j.external_user_id,
                j.status,
                j.send_at,
                j.sent_at,
                j.failure_reason,
                j.created_at,
                COALESCE(d.delivery_count, 0) AS delivery_count,
                COALESCE(d.failed_delivery_count, 0) AS failed_delivery_count
            FROM fixed_auto_reply_jobs j
            JOIN fixed_auto_reply_rules r ON r.id = j.rule_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) AS delivery_count,
                    COUNT(*) FILTER (WHERE d.status <> 'sent') AS failed_delivery_count
                FROM fixed_auto_reply_deliveries d
                WHERE d.job_id = j.id
            ) d ON TRUE
            ORDER BY j.created_at DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return {"items": [_row_to_dict(row) for row in rows.fetchall()]}



def _overview_period_payload(range_key: str, target_date: date | None) -> dict[str, Any]:
    return {
        "range": range_key,
        "date": target_date.isoformat() if target_date else None,
    }


async def _load_overview_part(
    *,
    part: str,
    range_key: str,
    target_date: date | None,
    force_refresh: bool,
    ttl_seconds: int,
    loader,
) -> dict[str, Any]:
    cache_key = _overview_part_cache_key(part, range_key, target_date)
    if not force_refresh:
        cached = await _get_cached_part(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    payload = await loader()
    payload["cached"] = False
    payload["period"] = _overview_period_payload(range_key, target_date)
    await _set_cached_part(cache_key, payload, ttl_seconds=ttl_seconds)
    return payload


@router.get("/overview/summary")
async def get_overview_summary(
    range_key: str = Query(default="today", alias="range"),
    target_date: date | None = Query(default=None, alias="date"),
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    _validate_overview_range(range_key, target_date)

    async def _loader() -> dict[str, Any]:
        summary = await fetch_overview_summary(db, range_key=range_key, target_date=target_date)
        return {"summary": _row_to_dict(summary) if summary else {}}

    return await _load_overview_part(
        part="summary",
        range_key=range_key,
        target_date=target_date,
        force_refresh=force_refresh,
        ttl_seconds=OVERVIEW_CACHE_TTL_SECONDS,
        loader=_loader,
    )


@router.get("/overview/accounts")
async def get_overview_accounts(
    range_key: str = Query(default="today", alias="range"),
    target_date: date | None = Query(default=None, alias="date"),
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    _validate_overview_range(range_key, target_date)

    async def _loader() -> dict[str, Any]:
        accounts = await fetch_overview_accounts(db, range_key=range_key, target_date=target_date)
        return {"accounts": [_row_to_dict(row) for row in accounts]}

    return await _load_overview_part(
        part="accounts",
        range_key=range_key,
        target_date=target_date,
        force_refresh=force_refresh,
        ttl_seconds=OVERVIEW_DETAILS_CACHE_TTL_SECONDS,
        loader=_loader,
    )


@router.get("/overview/rules")
async def get_overview_rules(
    range_key: str = Query(default="today", alias="range"),
    target_date: date | None = Query(default=None, alias="date"),
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    _validate_overview_range(range_key, target_date)

    async def _loader() -> dict[str, Any]:
        rules = await fetch_overview_rules(db, range_key=range_key, target_date=target_date)
        return {"rules": [_row_to_dict(row) for row in rules]}

    return await _load_overview_part(
        part="rules",
        range_key=range_key,
        target_date=target_date,
        force_refresh=force_refresh,
        ttl_seconds=OVERVIEW_DETAILS_CACHE_TTL_SECONDS,
        loader=_loader,
    )


@router.get("/overview/failures")
async def get_overview_failures(
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await ensure_schema(db)
    cache_key = "fixed-auto-replies:overview:failures:v1"

    if not force_refresh:
        cached = await _get_cached_part(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    failures = await fetch_overview_failures(db)
    payload = {
        "cached": False,
        "failures": [_row_to_dict(row) for row in failures],
    }
    await _set_cached_part(cache_key, payload, ttl_seconds=OVERVIEW_DETAILS_CACHE_TTL_SECONDS)
    return payload


@router.get("/overview")
async def get_overview(
    range_key: str = Query(default="today", alias="range"),
    target_date: date | None = Query(default=None, alias="date"),
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """Legacy combined overview; prefer split endpoints for faster page loads."""
    await ensure_schema(db)
    _validate_overview_range(range_key, target_date)

    cache_key = _overview_cache_key(range_key, target_date)
    if not force_refresh:
        cached = await _get_cached_overview(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

    summary = await fetch_overview_summary(db, range_key=range_key, target_date=target_date)
    accounts = await fetch_overview_accounts(db, range_key=range_key, target_date=target_date)
    rules = await fetch_overview_rules(db, range_key=range_key, target_date=target_date)
    failures = await fetch_overview_failures(db)

    payload = {
        "cached": False,
        "period": _overview_period_payload(range_key, target_date),
        "summary": _row_to_dict(summary) if summary else {},
        "accounts": [_row_to_dict(row) for row in accounts],
        "rules": [_row_to_dict(row) for row in rules],
        "failures": [_row_to_dict(row) for row in failures],
    }
    await _set_cached_overview(cache_key, payload)
    return payload


@router.post("/run-once")
@router.post("/run-once")
async def run_once(_operator: dict = Depends(require_operator)):
    result = await run_fixed_auto_reply_tick()
    return {"ok": True, **result}
