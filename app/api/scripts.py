from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db

router = APIRouter()

SCRIPT_REVIEW_STATUSES = {"draft", "approved", "archived"}


class ScriptBase(BaseModel):
    character_id: Optional[str] = None
    language: str = Field(default="en", min_length=1, max_length=10)
    relationship_stage: Optional[str] = Field(default=None, max_length=10)
    emotion_state: Optional[str] = Field(default=None, max_length=30)
    loneliness_score_min: float = Field(default=0, ge=0, le=100)
    loneliness_score_max: float = Field(default=100, ge=0, le=100)
    script_type: Optional[str] = Field(default=None, max_length=30)
    content: str = Field(..., min_length=1)
    risk_level: str = Field(default="low", min_length=1, max_length=10)
    conversion_goal: Optional[str] = Field(default=None, max_length=50)
    review_status: str = Field(default="draft", min_length=1, max_length=20)
    forbidden_scenarios: list[Any] = Field(default_factory=list)


class ScriptCreate(ScriptBase):
    pass


class ScriptUpdate(BaseModel):
    character_id: Optional[str] = None
    language: Optional[str] = Field(default=None, min_length=1, max_length=10)
    relationship_stage: Optional[str] = Field(default=None, max_length=10)
    emotion_state: Optional[str] = Field(default=None, max_length=30)
    loneliness_score_min: Optional[float] = Field(default=None, ge=0, le=100)
    loneliness_score_max: Optional[float] = Field(default=None, ge=0, le=100)
    script_type: Optional[str] = Field(default=None, max_length=30)
    content: Optional[str] = Field(default=None, min_length=1)
    risk_level: Optional[str] = Field(default=None, min_length=1, max_length=10)
    conversion_goal: Optional[str] = Field(default=None, max_length=50)
    review_status: Optional[str] = Field(default=None, min_length=1, max_length=20)
    forbidden_scenarios: Optional[list[Any]] = None


class ScriptSuggestRequest(BaseModel):
    character_id: Optional[str] = None
    language: str = Field(default="en", min_length=1, max_length=10)
    relationship_stage: Optional[str] = None
    emotion_state: Optional[str] = None
    loneliness_score: Optional[float] = Field(default=None, ge=0, le=100)
    script_type: Optional[str] = None
    risk_level: Optional[str] = None
    conversion_goal: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=20)


def _validate_uuid(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a valid UUID"
        ) from exc


def _validate_script_payload(data: ScriptBase | ScriptUpdate) -> None:
    lo = getattr(data, "loneliness_score_min", None)
    hi = getattr(data, "loneliness_score_max", None)
    if lo is not None and hi is not None and float(lo) > float(hi):
        raise HTTPException(
            status_code=422,
            detail="loneliness_score_min must be <= loneliness_score_max",
        )
    review_status = getattr(data, "review_status", None)
    if review_status is not None and review_status not in SCRIPT_REVIEW_STATUSES:
        raise HTTPException(status_code=422, detail="invalid review_status")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


@router.get("")
async def list_scripts(
    language: Optional[str] = Query(default=None, max_length=10),
    relationship_stage: Optional[str] = Query(default=None, max_length=10),
    script_type: Optional[str] = Query(default=None, max_length=30),
    review_status: Optional[str] = Query(default=None, max_length=20),
    character_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    cid = _validate_uuid(character_id, "character_id")
    if review_status is not None and review_status not in SCRIPT_REVIEW_STATUSES:
        raise HTTPException(status_code=422, detail="invalid review_status")

    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if language:
        clauses.append("language = :language")
        params["language"] = language
    if relationship_stage:
        clauses.append("relationship_stage = :relationship_stage")
        params["relationship_stage"] = relationship_stage
    if script_type:
        clauses.append("script_type = :script_type")
        params["script_type"] = script_type
    if review_status:
        clauses.append("review_status = :review_status")
        params["review_status"] = review_status
    if cid:
        clauses.append("character_id = CAST(:character_id AS uuid)")
        params["character_id"] = cid

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    res = await db.execute(
        text(
            f"""
            SELECT *
            FROM scripts
            {where}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    return {
        "items": [_row_to_dict(r) for r in res.fetchall()],
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_script(
    data: ScriptCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    _validate_script_payload(data)
    cid = _validate_uuid(data.character_id, "character_id")
    res = await db.execute(
        text(
            """
            INSERT INTO scripts (
              id, character_id, language, relationship_stage, emotion_state,
              loneliness_score_min, loneliness_score_max, script_type, content,
              risk_level, conversion_goal, review_status, forbidden_scenarios
            ) VALUES (
              :id, CAST(:character_id AS uuid), :language,
              :relationship_stage, :emotion_state,
              :loneliness_score_min, :loneliness_score_max, :script_type, :content,
              :risk_level, :conversion_goal, :review_status,
              CAST(:forbidden_scenarios AS jsonb)
            )
            RETURNING *
            """
        ),
        {
            **data.model_dump(exclude={"character_id", "forbidden_scenarios"}),
            "id": str(uuid.uuid4()),
            "character_id": cid,
            "forbidden_scenarios": json.dumps(
                data.forbidden_scenarios, ensure_ascii=False
            ),
        },
    )
    await db.commit()
    return _row_to_dict(res.fetchone())


@router.get("/{script_id}")
async def get_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    sid = _validate_uuid(script_id, "script_id")
    row = (
        await db.execute(
            text("SELECT * FROM scripts WHERE id = CAST(:id AS uuid)"),
            {"id": sid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script not found")
    return _row_to_dict(row)


@router.patch("/{script_id}")
async def update_script(
    script_id: str,
    data: ScriptUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    sid = _validate_uuid(script_id, "script_id")
    _validate_script_payload(data)
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await get_script(script_id, db, _operator)

    if "character_id" in values:
        values["character_id"] = _validate_uuid(
            values["character_id"], "character_id"
        )
    if "forbidden_scenarios" in values:
        values["forbidden_scenarios"] = json.dumps(
            values["forbidden_scenarios"], ensure_ascii=False
        )

    casts = {
        "character_id": "CAST(:character_id AS uuid)",
        "forbidden_scenarios": "CAST(:forbidden_scenarios AS jsonb)",
    }
    assignments = [f"{name} = {casts.get(name, ':' + name)}" for name in values]
    values["id"] = sid

    row = (
        await db.execute(
            text(
                f"""
                UPDATE scripts
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script not found")
    await db.commit()
    return _row_to_dict(row)


@router.delete("/{script_id}")
async def delete_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    sid = _validate_uuid(script_id, "script_id")
    row = (
        await db.execute(
            text("DELETE FROM scripts WHERE id = CAST(:id AS uuid) RETURNING id"),
            {"id": sid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="script not found")
    await db.commit()
    return {"status": "deleted", "script_id": sid}


@router.post("/suggest")
async def suggest_scripts(
    data: ScriptSuggestRequest,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    cid = _validate_uuid(data.character_id, "character_id")
    params = data.model_dump()
    params["character_id"] = cid

    clauses = ["review_status = 'approved'", "language = :language"]
    if data.script_type:
        clauses.append("script_type = :script_type")
    if cid:
        clauses.append(
            "(character_id = CAST(:character_id AS uuid) OR character_id IS NULL)"
        )
    if data.relationship_stage:
        clauses.append(
            "(relationship_stage = :relationship_stage OR relationship_stage IS NULL)"
        )
    if data.emotion_state:
        clauses.append("(emotion_state = :emotion_state OR emotion_state IS NULL)")
    if data.risk_level:
        clauses.append("(risk_level = :risk_level OR risk_level IS NULL)")
    if data.conversion_goal:
        clauses.append("(conversion_goal = :conversion_goal OR conversion_goal IS NULL)")
    if data.loneliness_score is not None:
        clauses.append(
            ":loneliness_score BETWEEN COALESCE(loneliness_score_min, 0) "
            "AND COALESCE(loneliness_score_max, 100)"
        )

    res = await db.execute(
        text(
            f"""
            SELECT *,
              (
                CASE
                  WHEN :character_id IS NOT NULL
                   AND character_id = CAST(:character_id AS uuid)
                  THEN 30 ELSE 0
                END +
                CASE
                  WHEN :relationship_stage IS NOT NULL
                   AND relationship_stage = :relationship_stage
                  THEN 20 ELSE 0
                END +
                CASE
                  WHEN :emotion_state IS NOT NULL AND emotion_state = :emotion_state
                  THEN 15 ELSE 0
                END +
                CASE
                  WHEN :loneliness_score IS NOT NULL
                   AND :loneliness_score BETWEEN COALESCE(loneliness_score_min, 0)
                   AND COALESCE(loneliness_score_max, 100)
                  THEN 15 ELSE 0
                END +
                CASE
                  WHEN :risk_level IS NOT NULL AND risk_level = :risk_level
                  THEN 10 ELSE 0
                END +
                CASE
                  WHEN :conversion_goal IS NOT NULL AND conversion_goal = :conversion_goal
                  THEN 10 ELSE 0
                END
              ) AS match_score
            FROM scripts
            WHERE {' AND '.join(clauses)}
            ORDER BY match_score DESC, updated_at DESC, created_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return {"items": [_row_to_dict(r) for r in res.fetchall()]}
