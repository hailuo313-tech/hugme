from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db

router = APIRouter()

QUALITY_RESULTS = {"passed", "needs_review", "failed"}
ISSUE_TAGS = {
    "tone_issue",
    "unsafe_advice",
    "policy_violation",
    "slow_response",
    "wrong_info",
    "missed_escalation",
    "other",
}


def _validate_uuid(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a valid UUID"
        ) from exc


def _reviewer_id(payload: dict[str, Any]) -> str:
    subject = payload.get("sub")
    try:
        return str(uuid.UUID(str(subject)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator token subject must be a valid UUID",
        ) from exc


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    tags = data.get("issue_tags")
    if isinstance(tags, str):
        data["issue_tags"] = json.loads(tags)
    return data


class QualityScoreCreate(BaseModel):
    handoff_task_id: Optional[str] = None
    operator_id: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    overall_score: int = Field(..., ge=0, le=100)
    empathy_score: Optional[int] = Field(default=None, ge=0, le=100)
    accuracy_score: Optional[int] = Field(default=None, ge=0, le=100)
    safety_score: Optional[int] = Field(default=None, ge=0, le=100)
    timeliness_score: Optional[int] = Field(default=None, ge=0, le=100)
    result: str = "needs_review"
    issue_tags: list[str] = Field(default_factory=list)
    review_notes: Optional[str] = None

    @field_validator("result")
    @classmethod
    def _validate_result(cls, value: str) -> str:
        if value not in QUALITY_RESULTS:
            raise ValueError("invalid result")
        return value

    @field_validator("issue_tags")
    @classmethod
    def _validate_issue_tags(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - ISSUE_TAGS)
        if unknown:
            raise ValueError(f"invalid issue_tags: {', '.join(unknown)}")
        return value


class QualityScorePatch(BaseModel):
    overall_score: Optional[int] = Field(default=None, ge=0, le=100)
    empathy_score: Optional[int] = Field(default=None, ge=0, le=100)
    accuracy_score: Optional[int] = Field(default=None, ge=0, le=100)
    safety_score: Optional[int] = Field(default=None, ge=0, le=100)
    timeliness_score: Optional[int] = Field(default=None, ge=0, le=100)
    result: Optional[str] = None
    issue_tags: Optional[list[str]] = None
    review_notes: Optional[str] = None

    @field_validator("result")
    @classmethod
    def _validate_result(cls, value: str | None) -> str | None:
        if value is not None and value not in QUALITY_RESULTS:
            raise ValueError("invalid result")
        return value

    @field_validator("issue_tags")
    @classmethod
    def _validate_issue_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - ISSUE_TAGS)
        if unknown:
            raise ValueError(f"invalid issue_tags: {', '.join(unknown)}")
        return value


async def _ensure_handoff_exists(db: AsyncSession, handoff_task_id: str | None) -> None:
    if not handoff_task_id:
        return
    row = (
        await db.execute(
            text("SELECT id FROM handoff_tasks WHERE id = CAST(:id AS uuid)"),
            {"id": handoff_task_id},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="handoff_task not found")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_quality_score(
    data: QualityScoreCreate,
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    ids = {
        "handoff_task_id": _validate_uuid(data.handoff_task_id, "handoff_task_id"),
        "operator_id": _validate_uuid(data.operator_id, "operator_id"),
        "reviewer_operator_id": _reviewer_id(operator),
        "conversation_id": _validate_uuid(data.conversation_id, "conversation_id"),
        "user_id": _validate_uuid(data.user_id, "user_id"),
        "message_id": _validate_uuid(data.message_id, "message_id"),
    }
    await _ensure_handoff_exists(db, ids["handoff_task_id"])

    row = (
        await db.execute(
            text(
                """
                INSERT INTO operator_quality_scores (
                  handoff_task_id, operator_id, reviewer_operator_id,
                  conversation_id, user_id, message_id,
                  overall_score, empathy_score, accuracy_score, safety_score,
                  timeliness_score, result, issue_tags, review_notes
                ) VALUES (
                  CAST(:handoff_task_id AS uuid), CAST(:operator_id AS uuid),
                  CAST(:reviewer_operator_id AS uuid), CAST(:conversation_id AS uuid),
                  CAST(:user_id AS uuid), CAST(:message_id AS uuid),
                  :overall_score, :empathy_score, :accuracy_score, :safety_score,
                  :timeliness_score, :result, CAST(:issue_tags AS jsonb), :review_notes
                )
                RETURNING *
                """
            ),
            {
                **ids,
                "overall_score": data.overall_score,
                "empathy_score": data.empathy_score,
                "accuracy_score": data.accuracy_score,
                "safety_score": data.safety_score,
                "timeliness_score": data.timeliness_score,
                "result": data.result,
                "issue_tags": json.dumps(data.issue_tags, ensure_ascii=False),
                "review_notes": data.review_notes,
            },
        )
    ).fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.get("")
async def list_quality_scores(
    operator_id: Optional[str] = Query(default=None),
    handoff_task_id: Optional[str] = Query(default=None),
    conversation_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    filters = {
        "operator_id": _validate_uuid(operator_id, "operator_id"),
        "handoff_task_id": _validate_uuid(handoff_task_id, "handoff_task_id"),
        "conversation_id": _validate_uuid(conversation_id, "conversation_id"),
        "user_id": _validate_uuid(user_id, "user_id"),
    }
    if result is not None and result not in QUALITY_RESULTS:
        raise HTTPException(status_code=422, detail="invalid result")

    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    for name, value in filters.items():
        if value:
            clauses.append(f"{name} = CAST(:{name} AS uuid)")
            params[name] = value
    if result:
        clauses.append("result = :result")
        params["result"] = result

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT *
                FROM operator_quality_scores
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()
    return {
        "items": [_row_to_dict(row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{quality_id}")
async def get_quality_score(
    quality_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    qid = _validate_uuid(quality_id, "quality_id")
    row = (
        await db.execute(
            text(
                """
                SELECT *
                FROM operator_quality_scores
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": qid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="quality score not found")
    return _row_to_dict(row)


@router.patch("/{quality_id}")
async def patch_quality_score(
    quality_id: str,
    data: QualityScorePatch,
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    qid = _validate_uuid(quality_id, "quality_id")
    reviewer_id = _reviewer_id(operator)
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await get_quality_score(quality_id, db, operator)

    if "issue_tags" in values:
        values["issue_tags"] = json.dumps(values["issue_tags"], ensure_ascii=False)

    casts = {"issue_tags": "CAST(:issue_tags AS jsonb)"}
    assignments = [f"{name} = {casts.get(name, ':' + name)}" for name in values]
    assignments.append("reviewer_operator_id = CAST(:reviewer_operator_id AS uuid)")
    values["id"] = qid
    values["reviewer_operator_id"] = reviewer_id

    row = (
        await db.execute(
            text(
                f"""
                UPDATE operator_quality_scores
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="quality score not found")
    await db.commit()
    return _row_to_dict(row)
