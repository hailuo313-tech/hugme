from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db
from core.config import settings

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _config_path(filename: str) -> Path:
    env_dir = os.environ.get("ERIS_CONFIG_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir) / filename)
    candidates.extend(
        [
            REPO_ROOT / "config" / filename,
            Path(__file__).resolve().parents[1] / "config" / filename,
            Path("/app/config") / filename,
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


INTENT_RULES_PATH = _config_path("intent_keyword_rules.json")
SAFETY_REDLINES_PATH = _config_path("safety_filter_redlines.json")

SCRIPT_STATUSES = {"draft", "approved", "archived"}
PERSONA_STATUSES = {"draft", "active", "inactive", "archived"}
SCRIPT_ASSET_TYPES = {"image", "video", "voice", "audio"}
SCRIPT_ASSET_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video": {".mp4", ".mov", ".webm", ".m4v"},
    "voice": {".ogg", ".oga", ".opus", ".m4a", ".mp3", ".wav"},
    "audio": {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".aac"},
}


class ScriptTemplatePayload(BaseModel):
    category_key: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=160)
    language: str = Field(default="en", min_length=1, max_length=10)
    channel: str = Field(default="telegram_real_user", min_length=1, max_length=40)
    platform: str = Field(default="telegram_real_user", min_length=1, max_length=40)
    user_level: str | None = Field(default=None, pattern="^[SABCD]$")
    chat_route: str | None = Field(default=None, max_length=30)
    persona_slug: str | None = Field(default=None, max_length=80)
    hook: str | None = Field(default=None, max_length=40)
    content: str = Field(..., min_length=1)
    operator_translation_zh: str | None = None
    variables: list[Any] = Field(default_factory=list)
    safety_tags: list[Any] = Field(default_factory=list)
    status: str = Field(default="draft", min_length=1, max_length=20)


class ScriptTemplateUpdate(BaseModel):
    category_key: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    language: str | None = Field(default=None, min_length=1, max_length=10)
    channel: str | None = Field(default=None, min_length=1, max_length=40)
    platform: str | None = Field(default=None, min_length=1, max_length=40)
    user_level: str | None = Field(default=None, pattern="^[SABCD]$")
    chat_route: str | None = Field(default=None, max_length=30)
    persona_slug: str | None = Field(default=None, max_length=80)
    hook: str | None = Field(default=None, max_length=40)
    content: str | None = Field(default=None, min_length=1)
    operator_translation_zh: str | None = None
    variables: list[Any] | None = None
    safety_tags: list[Any] | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)


class PersonaPromptPayload(BaseModel):
    slug: str = Field(..., min_length=1, max_length=80)
    display_name: str = Field(..., min_length=1, max_length=120)
    language: str = Field(default="zh", min_length=1, max_length=10)
    tone_family: str = Field(..., min_length=1, max_length=30)
    prompt_text: str = Field(..., min_length=1)
    safety_notes: list[str] = Field(default_factory=list)
    status: str = Field(default="active", min_length=1, max_length=20)


class PersonaPromptUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    language: str | None = Field(default=None, min_length=1, max_length=10)
    tone_family: str | None = Field(default=None, min_length=1, max_length=30)
    prompt_text: str | None = Field(default=None, min_length=1)
    safety_notes: list[str] | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)


class IntentRulePayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=120)
    intent: str = Field(..., min_length=1, max_length=120)
    priority: int = Field(default=0, ge=0, le=1000)
    confidence: float = Field(default=0.75, ge=0, le=1)
    keywords: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    enabled: bool = True


class RedlinePayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=120)
    category: str = Field(..., min_length=1, max_length=120)
    reason: str = Field(..., min_length=1, max_length=160)
    patterns: list[str] = Field(..., min_length=1)
    enabled: bool = True


class AppDownloadPlatformPayload(BaseModel):
    platform_key: str = Field(..., min_length=1, max_length=40, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=80)
    download_url: str = Field(..., min_length=1)
    is_active: bool = True
    is_default: bool = False
    sort_order: int = Field(default=0, ge=0, le=1000)


class AppDownloadPlatformUpdate(BaseModel):
    platform_key: str | None = Field(default=None, min_length=1, max_length=40, pattern="^[a-zA-Z0-9_-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    download_url: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    is_default: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)


def _row(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid UUID") from exc


def _validate_status(value: str | None, allowed: set[str], field_name: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(status_code=422, detail=f"invalid {field_name}")


def _validate_asset_type(value: str) -> str:
    asset_type = str(value or "").strip().lower()
    if asset_type not in SCRIPT_ASSET_TYPES:
        raise HTTPException(status_code=422, detail="invalid asset_type")
    return asset_type


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"{path.name} not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"{path.name} is invalid JSON") from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _ensure_unique(items: list[dict[str, Any]], item_id: str, *, ignore_index: int | None = None) -> None:
    for index, item in enumerate(items):
        if ignore_index is not None and index == ignore_index:
            continue
        if str(item.get("id")) == item_id:
            raise HTTPException(status_code=409, detail=f"duplicate id: {item_id}")


def _validate_regexes(patterns: list[str]) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise HTTPException(status_code=422, detail=f"invalid regex: {pattern}") from exc


def _validate_http_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="download_url must be an absolute http(s) URL")
    return url


def _public_asset_url(filename: str) -> str:
    base = str(settings.PUBLIC_BASE_URL or "").rstrip("/")
    path = str(settings.MEDIA_PUBLIC_PATH or "/uploads").rstrip("/")
    return f"{base}{path}/script-assets/{filename}"


def _script_asset_dir() -> Path:
    path = Path(settings.MEDIA_UPLOAD_DIR) / "script-assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_ext(filename: str | None, asset_type: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SCRIPT_ASSET_EXTENSIONS[asset_type]:
        raise HTTPException(status_code=422, detail=f"unsupported {asset_type} file type")
    return suffix


async def _assets_for_templates(db: AsyncSession, template_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not template_ids:
        return {}
    result = await db.execute(
        text(
            """
            SELECT id, script_template_id, asset_type, asset_url, original_filename,
                   mime_type, file_size_bytes, caption, sort_order, created_at, updated_at
            FROM script_template_assets
            WHERE is_active = TRUE
              AND script_template_id::text = ANY(:ids)
            ORDER BY sort_order ASC, created_at ASC
            """
        ),
        {"ids": template_ids},
    )
    by_template: dict[str, list[dict[str, Any]]] = {tid: [] for tid in template_ids}
    for row in result.fetchall():
        item = _row(row)
        tid = str(item.pop("script_template_id"))
        by_template.setdefault(tid, []).append(item)
    return by_template


async def _attach_assets(db: AsyncSession, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = await _assets_for_templates(db, [str(item["id"]) for item in items])
    for item in items:
        item["assets"] = assets.get(str(item["id"]), [])
    return items


@router.get("/script-templates")
async def list_script_templates(
    category_key: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    persona_slug: str | None = Query(default=None, max_length=80),
    hook: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if category_key:
        clauses.append("category_key = :category_key")
        params["category_key"] = category_key
    if status_filter:
        _validate_status(status_filter, SCRIPT_STATUSES, "status")
        clauses.append("status = :status")
        params["status"] = status_filter
    if persona_slug:
        clauses.append("persona_slug = :persona_slug")
        params["persona_slug"] = persona_slug
    if hook:
        clauses.append("hook = :hook")
        params["hook"] = hook
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    result = await db.execute(
        text(
            f"""
            SELECT *
            FROM script_templates
            {where}
            ORDER BY created_at DESC, updated_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    items = [_row(row) for row in result.fetchall()]
    return {"items": await _attach_assets(db, items), "limit": limit, "offset": offset}


@router.post("/script-templates", status_code=status.HTTP_201_CREATED)
async def create_script_template(
    payload: ScriptTemplatePayload,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    _validate_status(payload.status, SCRIPT_STATUSES, "status")
    result = await db.execute(
        text(
            """
            INSERT INTO script_templates (
              id, category_key, title, language, channel, platform, user_level,
              chat_route, persona_slug, hook, content, operator_translation_zh,
              variables, safety_tags, status
            ) VALUES (
              :id, :category_key, :title, :language, :channel, :platform, :user_level,
              :chat_route, :persona_slug, :hook, :content, :operator_translation_zh,
              CAST(:variables AS jsonb), CAST(:safety_tags AS jsonb), :status
            )
            RETURNING *
            """
        ),
        {
            **payload.model_dump(exclude={"variables", "safety_tags"}),
            "id": str(uuid.uuid4()),
            "variables": _json_dump(payload.variables),
            "safety_tags": _json_dump(payload.safety_tags),
        },
    )
    await db.commit()
    return (await _attach_assets(db, [_row(result.fetchone())]))[0]


@router.patch("/script-templates/{template_id}")
async def update_script_template(
    template_id: str,
    payload: ScriptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    tid = _validate_uuid(template_id, "template_id")
    values = payload.model_dump(exclude_unset=True)
    _validate_status(values.get("status"), SCRIPT_STATUSES, "status")
    if not values:
        row = (await db.execute(text("SELECT * FROM script_templates WHERE id = CAST(:id AS uuid)"), {"id": tid})).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="script template not found")
        return _row(row)
    for key in ("variables", "safety_tags"):
        if key in values:
            values[key] = _json_dump(values[key])
    casts = {"variables": "CAST(:variables AS jsonb)", "safety_tags": "CAST(:safety_tags AS jsonb)"}
    assignments = [f"{key} = {casts.get(key, ':' + key)}" for key in values]
    values["id"] = tid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE script_templates
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script template not found")
    await db.commit()
    return (await _attach_assets(db, [_row(row)]))[0]


@router.delete("/script-templates/{template_id}")
async def delete_script_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    tid = _validate_uuid(template_id, "template_id")
    row = (
        await db.execute(
            text(
                """
                UPDATE script_templates
                SET status = 'archived', updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id
                """
            ),
            {"id": tid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script template not found")
    await db.commit()
    return {"status": "archived", "id": tid}


@router.get("/script-templates/{template_id}/assets")
async def list_script_template_assets(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    tid = _validate_uuid(template_id, "template_id")
    return {"items": (await _assets_for_templates(db, [tid])).get(tid, [])}


@router.post("/script-templates/{template_id}/assets", status_code=status.HTTP_201_CREATED)
async def upload_script_template_asset(
    template_id: str,
    asset_type: str = Form(...),
    caption: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    tid = _validate_uuid(template_id, "template_id")
    kind = _validate_asset_type(asset_type)
    suffix = _safe_ext(file.filename, kind)
    exists = (
        await db.execute(
            text("SELECT 1 FROM script_templates WHERE id = CAST(:id AS uuid)"),
            {"id": tid},
        )
    ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="script template not found")

    asset_id = str(uuid.uuid4())
    filename = f"{asset_id}{suffix}"
    target = _script_asset_dir() / filename
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    max_bytes = 50 * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="file too large")
    target.write_bytes(content)

    next_order = (
        await db.execute(
            text(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1
                FROM script_template_assets
                WHERE script_template_id = CAST(:tid AS uuid)
                  AND is_active = TRUE
                """
            ),
            {"tid": tid},
        )
    ).scalar()
    row = (
        await db.execute(
            text(
                """
                INSERT INTO script_template_assets (
                    id, script_template_id, asset_type, asset_url, storage_path,
                    original_filename, mime_type, file_size_bytes, caption, sort_order
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), :asset_type, :asset_url, :storage_path,
                    :original_filename, :mime_type, :file_size_bytes, :caption, :sort_order
                )
                RETURNING id, script_template_id, asset_type, asset_url, original_filename,
                          mime_type, file_size_bytes, caption, sort_order, created_at, updated_at
                """
            ),
            {
                "id": asset_id,
                "tid": tid,
                "asset_type": kind,
                "asset_url": _public_asset_url(filename),
                "storage_path": str(target),
                "original_filename": file.filename or filename,
                "mime_type": file.content_type,
                "file_size_bytes": len(content),
                "caption": caption,
                "sort_order": int(next_order or 0),
            },
        )
    ).fetchone()
    await db.commit()
    item = _row(row)
    item.pop("script_template_id", None)
    return item


@router.patch("/script-template-assets/{asset_id}")
async def update_script_template_asset(
    asset_id: str,
    sort_order: int | None = None,
    caption: str | None = None,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    aid = _validate_uuid(asset_id, "asset_id")
    values: dict[str, Any] = {"id": aid}
    assignments: list[str] = []
    if sort_order is not None:
        values["sort_order"] = int(sort_order)
        assignments.append("sort_order = :sort_order")
    if caption is not None:
        values["caption"] = caption
        assignments.append("caption = :caption")
    if not assignments:
        row = (await db.execute(text("SELECT * FROM script_template_assets WHERE id = CAST(:id AS uuid)"), values)).fetchone()
    else:
        row = (
            await db.execute(
                text(
                    f"""
                    UPDATE script_template_assets
                    SET {', '.join(assignments)}, updated_at = NOW()
                    WHERE id = CAST(:id AS uuid) AND is_active = TRUE
                    RETURNING *
                    """
                ),
                values,
            )
        ).fetchone()
        await db.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="script template asset not found")
    item = _row(row)
    item.pop("script_template_id", None)
    return item


@router.delete("/script-template-assets/{asset_id}")
async def delete_script_template_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    aid = _validate_uuid(asset_id, "asset_id")
    row = (
        await db.execute(
            text(
                """
                UPDATE script_template_assets
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING storage_path
                """
            ),
            {"id": aid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script template asset not found")
    await db.commit()
    return {"status": "deleted", "id": aid}


@router.get("/app-download-platforms")
async def list_app_download_platforms(
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT id, platform_key, display_name, download_url, is_active,
                       is_default, sort_order, created_at, updated_at
                FROM app_download_platforms
                ORDER BY sort_order ASC, is_default DESC, updated_at DESC
                """
            )
        )
    ).fetchall()
    return {"items": [_row(row) for row in rows]}


@router.post("/app-download-platforms", status_code=status.HTTP_201_CREATED)
async def create_app_download_platform(
    payload: AppDownloadPlatformPayload,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    download_url = _validate_http_url(payload.download_url)
    if payload.is_default:
        await db.execute(text("UPDATE app_download_platforms SET is_default = FALSE WHERE is_default = TRUE"))
    row = (
        await db.execute(
            text(
                """
                INSERT INTO app_download_platforms (
                    id, platform_key, display_name, download_url,
                    is_active, is_default, sort_order
                ) VALUES (
                    CAST(:id AS uuid), :platform_key, :display_name, :download_url,
                    :is_active, :is_default, :sort_order
                )
                RETURNING id, platform_key, display_name, download_url, is_active,
                          is_default, sort_order, created_at, updated_at
                """
            ),
            {
                **payload.model_dump(exclude={"download_url"}),
                "id": str(uuid.uuid4()),
                "download_url": download_url,
            },
        )
    ).fetchone()
    await db.commit()
    return _row(row)


@router.patch("/app-download-platforms/{platform_id}")
async def update_app_download_platform(
    platform_id: str,
    payload: AppDownloadPlatformUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    pid = _validate_uuid(platform_id, "platform_id")
    values = payload.model_dump(exclude_unset=True)
    if "download_url" in values:
        values["download_url"] = _validate_http_url(values["download_url"])
    if not values:
        row = (
            await db.execute(
                text(
                    """
                    SELECT id, platform_key, display_name, download_url, is_active,
                           is_default, sort_order, created_at, updated_at
                    FROM app_download_platforms
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": pid},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="app download platform not found")
        return _row(row)
    if values.get("is_default") is True:
        await db.execute(
            text("UPDATE app_download_platforms SET is_default = FALSE WHERE id <> CAST(:id AS uuid)"),
            {"id": pid},
        )
    assignments = [f"{key} = :{key}" for key in values]
    values["id"] = pid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE app_download_platforms
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id, platform_key, display_name, download_url, is_active,
                          is_default, sort_order, created_at, updated_at
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="app download platform not found")
    await db.commit()
    return _row(row)


@router.delete("/app-download-platforms/{platform_id}")
async def delete_app_download_platform(
    platform_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    pid = _validate_uuid(platform_id, "platform_id")
    row = (
        await db.execute(
            text(
                """
                DELETE FROM app_download_platforms
                WHERE id = CAST(:id AS uuid)
                RETURNING id
                """
            ),
            {"id": pid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="app download platform not found")
    await db.commit()
    return {"status": "deleted", "id": pid}


@router.get("/persona-prompts")
async def list_persona_prompts(
    include_archived: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    where = "" if include_archived else "WHERE status <> 'archived'"
    rows = (
        await db.execute(
            text(f"SELECT * FROM persona_prompts {where} ORDER BY updated_at DESC, created_at DESC")
        )
    ).fetchall()
    return {"items": [_row(row) for row in rows]}


@router.post("/persona-prompts", status_code=status.HTTP_201_CREATED)
async def create_persona_prompt(
    payload: PersonaPromptPayload,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    _validate_status(payload.status, PERSONA_STATUSES, "status")
    row = (
        await db.execute(
            text(
                """
                INSERT INTO persona_prompts (
                  id, slug, display_name, language, tone_family, prompt_text, safety_notes, status
                ) VALUES (
                  :id, :slug, :display_name, :language, :tone_family, :prompt_text,
                  CAST(:safety_notes AS jsonb), :status
                )
                RETURNING *
                """
            ),
            {
                **payload.model_dump(exclude={"safety_notes"}),
                "id": str(uuid.uuid4()),
                "safety_notes": _json_dump(payload.safety_notes),
            },
        )
    ).fetchone()
    await db.commit()
    return _row(row)


@router.patch("/persona-prompts/{prompt_id}")
async def update_persona_prompt(
    prompt_id: str,
    payload: PersonaPromptUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    pid = _validate_uuid(prompt_id, "prompt_id")
    values = payload.model_dump(exclude_unset=True)
    _validate_status(values.get("status"), PERSONA_STATUSES, "status")
    if "safety_notes" in values:
        values["safety_notes"] = _json_dump(values["safety_notes"])
    if not values:
        row = (await db.execute(text("SELECT * FROM persona_prompts WHERE id = CAST(:id AS uuid)"), {"id": pid})).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="persona prompt not found")
        return _row(row)
    casts = {"safety_notes": "CAST(:safety_notes AS jsonb)"}
    assignments = [f"{key} = {casts.get(key, ':' + key)}" for key in values]
    values["id"] = pid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE persona_prompts
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="persona prompt not found")
    await db.commit()
    return _row(row)


@router.delete("/persona-prompts/{prompt_id}")
async def delete_persona_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    pid = _validate_uuid(prompt_id, "prompt_id")
    row = (
        await db.execute(
            text(
                """
                UPDATE persona_prompts
                SET status = 'archived', updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id
                """
            ),
            {"id": pid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="persona prompt not found")
    await db.commit()
    return {"status": "archived", "id": pid}


@router.get("/intent-rules")
async def list_intent_rules(_operator: dict = Depends(require_operator)):
    data = _read_json(INTENT_RULES_PATH)
    return {
        "version": int(data.get("version", 1)),
        "confidence_floor": float(data.get("confidence_floor", 0.6)),
        "items": data.get("rules", []),
    }


@router.post("/intent-rules", status_code=status.HTTP_201_CREATED)
async def create_intent_rule(payload: IntentRulePayload, _operator: dict = Depends(require_operator)):
    data = _read_json(INTENT_RULES_PATH)
    rules = list(data.get("rules", []))
    _ensure_unique(rules, payload.id)
    _validate_regexes(payload.patterns)
    rules.append(payload.model_dump())
    data["rules"] = rules
    data["version"] = int(data.get("version", 1)) + 1
    _write_json(INTENT_RULES_PATH, data)
    return payload.model_dump()


@router.patch("/intent-rules/{rule_id}")
async def update_intent_rule(
    rule_id: str,
    payload: IntentRulePayload,
    _operator: dict = Depends(require_operator),
):
    data = _read_json(INTENT_RULES_PATH)
    rules = list(data.get("rules", []))
    for index, item in enumerate(rules):
        if str(item.get("id")) == rule_id:
            _ensure_unique(rules, payload.id, ignore_index=index)
            _validate_regexes(payload.patterns)
            rules[index] = payload.model_dump()
            data["rules"] = rules
            data["version"] = int(data.get("version", 1)) + 1
            _write_json(INTENT_RULES_PATH, data)
            return rules[index]
    raise HTTPException(status_code=404, detail="intent rule not found")


@router.delete("/intent-rules/{rule_id}")
async def delete_intent_rule(rule_id: str, _operator: dict = Depends(require_operator)):
    data = _read_json(INTENT_RULES_PATH)
    rules = list(data.get("rules", []))
    next_rules = [item for item in rules if str(item.get("id")) != rule_id]
    if len(next_rules) == len(rules):
        raise HTTPException(status_code=404, detail="intent rule not found")
    data["rules"] = next_rules
    data["version"] = int(data.get("version", 1)) + 1
    _write_json(INTENT_RULES_PATH, data)
    return {"status": "deleted", "id": rule_id}


@router.get("/redlines")
async def list_redlines(_operator: dict = Depends(require_operator)):
    data = _read_json(SAFETY_REDLINES_PATH)
    return {"version": int(data.get("version", 1)), "items": data.get("redlines", [])}


@router.post("/redlines", status_code=status.HTTP_201_CREATED)
async def create_redline(payload: RedlinePayload, _operator: dict = Depends(require_operator)):
    data = _read_json(SAFETY_REDLINES_PATH)
    redlines = list(data.get("redlines", []))
    _ensure_unique(redlines, payload.id)
    _validate_regexes(payload.patterns)
    redlines.append(payload.model_dump())
    data["redlines"] = redlines
    data["version"] = int(data.get("version", 1)) + 1
    _write_json(SAFETY_REDLINES_PATH, data)
    return payload.model_dump()


@router.patch("/redlines/{redline_id}")
async def update_redline(
    redline_id: str,
    payload: RedlinePayload,
    _operator: dict = Depends(require_operator),
):
    data = _read_json(SAFETY_REDLINES_PATH)
    redlines = list(data.get("redlines", []))
    for index, item in enumerate(redlines):
        if str(item.get("id")) == redline_id:
            _ensure_unique(redlines, payload.id, ignore_index=index)
            _validate_regexes(payload.patterns)
            redlines[index] = payload.model_dump()
            data["redlines"] = redlines
            data["version"] = int(data.get("version", 1)) + 1
            _write_json(SAFETY_REDLINES_PATH, data)
            return redlines[index]
    raise HTTPException(status_code=404, detail="redline not found")


@router.delete("/redlines/{redline_id}")
async def delete_redline(redline_id: str, _operator: dict = Depends(require_operator)):
    data = _read_json(SAFETY_REDLINES_PATH)
    redlines = list(data.get("redlines", []))
    next_redlines = [item for item in redlines if str(item.get("id")) != redline_id]
    if len(next_redlines) == len(redlines):
        raise HTTPException(status_code=404, detail="redline not found")
    data["redlines"] = next_redlines
    data["version"] = int(data.get("version", 1)) + 1
    _write_json(SAFETY_REDLINES_PATH, data)
    return {"status": "deleted", "id": redline_id}
