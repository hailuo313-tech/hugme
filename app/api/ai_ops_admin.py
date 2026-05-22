from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db

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


class ScriptTemplatePayload(BaseModel):
    category_key: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=160)
    language: str = Field(default="zh", min_length=1, max_length=10)
    channel: str = Field(default="telegram_real_user", min_length=1, max_length=40)
    platform: str = Field(default="telegram_real_user", min_length=1, max_length=40)
    user_level: str | None = Field(default=None, pattern="^[SABCD]$")
    chat_route: str | None = Field(default=None, max_length=30)
    persona_slug: str | None = Field(default=None, max_length=80)
    hook: str | None = Field(default=None, max_length=40)
    content: str = Field(..., min_length=1)
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
            ORDER BY updated_at DESC, created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    return {"items": [_row(row) for row in result.fetchall()], "limit": limit, "offset": offset}


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
              chat_route, persona_slug, hook, content, variables, safety_tags, status
            ) VALUES (
              :id, :category_key, :title, :language, :channel, :platform, :user_level,
              :chat_route, :persona_slug, :hook, :content,
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
    return _row(result.fetchone())


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
    return _row(row)


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
