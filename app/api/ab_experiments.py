from __future__ import annotations

import hashlib
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

EXPERIMENT_STATUSES = {"draft", "running", "paused", "archived"}


def _validate_uuid(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid UUID") from exc


def _operator_uuid(payload: dict[str, Any]) -> str:
    return _validate_uuid(str(payload.get("sub") or ""), "operator_id") or ""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    for field in ("target_rules", "config", "context", "metadata"):
        if isinstance(data.get(field), str):
            data[field] = json.loads(data[field])
    return data


def _validate_status(value: str | None) -> str | None:
    if value is not None and value not in EXPERIMENT_STATUSES:
        raise ValueError("invalid experiment status")
    return value


class ExperimentCreate(BaseModel):
    experiment_key: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=160)
    description: Optional[str] = None
    status: str = "draft"
    target_rules: dict[str, Any] = Field(default_factory=dict)
    start_at: Optional[str] = None
    end_at: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        return _validate_status(value) or value


class ExperimentPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    status: Optional[str] = None
    target_rules: Optional[dict[str, Any]] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        return _validate_status(value)


class VariantCreate(BaseModel):
    variant_key: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=160)
    weight: int = Field(default=0, ge=0, le=10000)
    config: dict[str, Any] = Field(default_factory=dict)
    is_control: bool = False


class VariantPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    weight: Optional[int] = Field(default=None, ge=0, le=10000)
    config: Optional[dict[str, Any]] = None
    is_control: Optional[bool] = None


class AssignmentRequest(BaseModel):
    user_id: Optional[str] = None
    assignment_key: Optional[str] = Field(default=None, min_length=1, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, value: str | None) -> str | None:
        return _validate_uuid(value, "user_id")


class EventCreate(BaseModel):
    variant_id: Optional[str] = None
    assignment_id: Optional[str] = None
    user_id: Optional[str] = None
    event_type: str = Field(..., min_length=1, max_length=80)
    event_value: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("variant_id")
    @classmethod
    def _variant_id(cls, value: str | None) -> str | None:
        return _validate_uuid(value, "variant_id")

    @field_validator("assignment_id")
    @classmethod
    def _assignment_id(cls, value: str | None) -> str | None:
        return _validate_uuid(value, "assignment_id")

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, value: str | None) -> str | None:
        return _validate_uuid(value, "user_id")


def _pick_variant(
    *, experiment_key: str, bucket_key: str, variants: list[dict[str, Any]]
) -> dict[str, Any]:
    weighted = [v for v in variants if int(v.get("weight") or 0) > 0]
    if not weighted:
        raise HTTPException(status_code=409, detail="experiment has no weighted variants")
    total = sum(int(v["weight"]) for v in weighted)
    digest = hashlib.sha256(f"{experiment_key}:{bucket_key}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % total
    running = 0
    for variant in weighted:
        running += int(variant["weight"])
        if bucket < running:
            return variant
    return weighted[-1]


@router.get("")
async def list_experiments(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    experiment_key: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    if status_filter is not None:
        _validate_status(status_filter)
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status_filter:
        clauses.append("status = :status")
        params["status"] = status_filter
    if experiment_key:
        clauses.append("experiment_key = :experiment_key")
        params["experiment_key"] = experiment_key
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT *
                FROM ab_experiments
                {where}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()
    return {"items": [_row_to_dict(row) for row in rows], "limit": limit, "offset": offset}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_experiment(
    data: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    operator: dict = Depends(require_operator),
):
    row = (
        await db.execute(
            text(
                """
                INSERT INTO ab_experiments (
                  id, experiment_key, name, description, status,
                  owner_operator_id, target_rules, start_at, end_at
                ) VALUES (
                  :id, :experiment_key, :name, :description, :status,
                  CAST(:owner_operator_id AS uuid), CAST(:target_rules AS jsonb),
                  CAST(:start_at AS timestamp), CAST(:end_at AS timestamp)
                )
                RETURNING *
                """
            ),
            {
                **data.model_dump(exclude={"target_rules"}),
                "id": str(uuid.uuid4()),
                "owner_operator_id": _operator_uuid(operator),
                "target_rules": _json_dumps(data.target_rules),
            },
        )
    ).fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    row = (
        await db.execute(
            text("SELECT * FROM ab_experiments WHERE id = CAST(:id AS uuid)"),
            {"id": eid},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return _row_to_dict(row)


@router.patch("/{experiment_id}")
async def patch_experiment(
    experiment_id: str,
    data: ExperimentPatch,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await get_experiment(experiment_id, db, _operator)
    if "target_rules" in values:
        values["target_rules"] = _json_dumps(values["target_rules"])
    casts = {
        "target_rules": "CAST(:target_rules AS jsonb)",
        "start_at": "CAST(:start_at AS timestamp)",
        "end_at": "CAST(:end_at AS timestamp)",
    }
    assignments = [f"{name} = {casts.get(name, ':' + name)}" for name in values]
    values["id"] = eid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE ab_experiments
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    await db.commit()
    return _row_to_dict(row)


@router.get("/{experiment_id}/variants")
async def list_variants(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    rows = (
        await db.execute(
            text(
                """
                SELECT *
                FROM ab_variants
                WHERE experiment_id = CAST(:experiment_id AS uuid)
                ORDER BY is_control DESC, variant_key ASC
                """
            ),
            {"experiment_id": eid},
        )
    ).fetchall()
    return {"items": [_row_to_dict(row) for row in rows]}


@router.post("/{experiment_id}/variants", status_code=status.HTTP_201_CREATED)
async def create_variant(
    experiment_id: str,
    data: VariantCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    row = (
        await db.execute(
            text(
                """
                INSERT INTO ab_variants (
                  id, experiment_id, variant_key, name, weight, config, is_control
                ) VALUES (
                  :id, CAST(:experiment_id AS uuid), :variant_key, :name,
                  :weight, CAST(:config AS jsonb), :is_control
                )
                RETURNING *
                """
            ),
            {
                **data.model_dump(exclude={"config"}),
                "id": str(uuid.uuid4()),
                "experiment_id": eid,
                "config": _json_dumps(data.config),
            },
        )
    ).fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.patch("/{experiment_id}/variants/{variant_id}")
async def patch_variant(
    experiment_id: str,
    variant_id: str,
    data: VariantPatch,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    vid = _validate_uuid(variant_id, "variant_id")
    values = data.model_dump(exclude_unset=True)
    if not values:
        row = (
            await db.execute(
                text(
                    """
                    SELECT *
                    FROM ab_variants
                    WHERE id = CAST(:id AS uuid)
                      AND experiment_id = CAST(:experiment_id AS uuid)
                    """
                ),
                {"id": vid, "experiment_id": eid},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="variant not found")
        return _row_to_dict(row)
    if "config" in values:
        values["config"] = _json_dumps(values["config"])
    assignments = [
        f"{name} = {'CAST(:config AS jsonb)' if name == 'config' else ':' + name}"
        for name in values
    ]
    values["id"] = vid
    values["experiment_id"] = eid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE ab_variants
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND experiment_id = CAST(:experiment_id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="variant not found")
    await db.commit()
    return _row_to_dict(row)


@router.post("/{experiment_id}/assign")
async def assign_variant(
    experiment_id: str,
    data: AssignmentRequest,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    if not data.user_id and not data.assignment_key:
        raise HTTPException(status_code=422, detail="user_id or assignment_key is required")
    bucket_key = data.user_id or data.assignment_key or ""

    existing = (
        await db.execute(
            text(
                """
                SELECT a.*, v.variant_key, v.name AS variant_name, v.config
                FROM ab_assignments a
                JOIN ab_variants v ON v.id = a.variant_id
                WHERE a.experiment_id = CAST(:experiment_id AS uuid)
                  AND (
                    (CAST(:user_id AS uuid) IS NOT NULL AND a.user_id = CAST(:user_id AS uuid))
                    OR (CAST(:assignment_key AS text) IS NOT NULL AND a.assignment_key = :assignment_key)
                  )
                """
            ),
            {"experiment_id": eid, "user_id": data.user_id, "assignment_key": data.assignment_key},
        )
    ).fetchone()
    if existing is not None:
        return {"assignment": _row_to_dict(existing), "created": False}

    exp_row = (
        await db.execute(
            text(
                """
                SELECT id, experiment_key, status
                FROM ab_experiments
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": eid},
        )
    ).fetchone()
    if exp_row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    experiment = _row_to_dict(exp_row)
    if experiment["status"] != "running":
        raise HTTPException(status_code=409, detail="experiment is not running")

    variant_rows = (
        await db.execute(
            text(
                """
                SELECT id, variant_key, name, weight, config, is_control
                FROM ab_variants
                WHERE experiment_id = CAST(:experiment_id AS uuid)
                ORDER BY variant_key ASC
                """
            ),
            {"experiment_id": eid},
        )
    ).fetchall()
    variants = [_row_to_dict(row) for row in variant_rows]
    chosen = _pick_variant(
        experiment_key=experiment["experiment_key"],
        bucket_key=bucket_key,
        variants=variants,
    )
    row = (
        await db.execute(
            text(
                """
                INSERT INTO ab_assignments (
                  id, experiment_id, variant_id, user_id, assignment_key, context
                ) VALUES (
                  :id, CAST(:experiment_id AS uuid), CAST(:variant_id AS uuid),
                  CAST(:user_id AS uuid), :assignment_key, CAST(:context AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "experiment_id": eid,
                "variant_id": chosen["id"],
                "user_id": data.user_id,
                "assignment_key": data.assignment_key,
                "context": _json_dumps(data.context),
            },
        )
    ).fetchone()
    await db.commit()
    assignment = _row_to_dict(row)
    assignment.update(
        {
            "variant_key": chosen["variant_key"],
            "variant_name": chosen["name"],
            "config": chosen.get("config") or {},
        }
    )
    return {"assignment": assignment, "created": True}


@router.post("/{experiment_id}/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    experiment_id: str,
    data: EventCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    row = (
        await db.execute(
            text(
                """
                INSERT INTO ab_events (
                  id, experiment_id, variant_id, assignment_id, user_id,
                  event_type, event_value, metadata
                ) VALUES (
                  :id, CAST(:experiment_id AS uuid), CAST(:variant_id AS uuid),
                  CAST(:assignment_id AS uuid), CAST(:user_id AS uuid),
                  :event_type, :event_value, CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                **data.model_dump(exclude={"metadata"}),
                "id": str(uuid.uuid4()),
                "experiment_id": eid,
                "metadata": _json_dumps(data.metadata),
            },
        )
    ).fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.get("/{experiment_id}/events")
async def list_events(
    experiment_id: str,
    event_type: Optional[str] = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    eid = _validate_uuid(experiment_id, "experiment_id")
    clauses = ["experiment_id = CAST(:experiment_id AS uuid)"]
    params: dict[str, Any] = {"experiment_id": eid, "limit": limit, "offset": offset}
    if event_type:
        clauses.append("event_type = :event_type")
        params["event_type"] = event_type
    rows = (
        await db.execute(
            text(
                f"""
                SELECT *
                FROM ab_events
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()
    return {"items": [_row_to_dict(row) for row in rows], "limit": limit, "offset": offset}
