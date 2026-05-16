from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import require_operator
from core.database import get_db

router = APIRouter()


CHARACTER_STATUSES = {"draft", "active", "archived", "inactive"}
REPLY_LENGTHS = {"short", "medium", "long"}
EMOJI_FREQUENCIES = {"none", "low", "medium", "high"}


class CharacterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    age_feel: Optional[str] = Field(default=None, max_length=50)
    region: Optional[str] = Field(default=None, max_length=50)
    occupation: Optional[str] = Field(default=None, max_length=100)
    background: Optional[str] = None
    relationship_position: Optional[str] = Field(default=None, max_length=100)
    default_language: str = Field(default="en", min_length=1, max_length=10)
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    gentle_score: int = Field(default=50, ge=0, le=100)
    proactive_score: int = Field(default=50, ge=0, le=100)
    flirt_score: int = Field(default=30, ge=0, le=100)
    humor_score: int = Field(default=40, ge=0, le=100)
    emotional_depth_score: int = Field(default=60, ge=0, le=100)
    boundary_score: int = Field(default=70, ge=0, le=100)
    reply_length: str = Field(default="medium", min_length=1, max_length=10)
    tone: str = Field(default="warm", min_length=1, max_length=20)
    emoji_frequency: str = Field(default="low", min_length=1, max_length=10)
    prompt_en: Optional[str] = None
    prompt_es: Optional[str] = None
    prompt_fr: Optional[str] = None
    prompt_de: Optional[str] = None
    status: str = Field(default="draft", min_length=1, max_length=20)


class CharacterCreate(CharacterBase):
    pass


class CharacterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    age_feel: Optional[str] = Field(default=None, max_length=50)
    region: Optional[str] = Field(default=None, max_length=50)
    occupation: Optional[str] = Field(default=None, max_length=100)
    background: Optional[str] = None
    relationship_position: Optional[str] = Field(default=None, max_length=100)
    default_language: Optional[str] = Field(default=None, min_length=1, max_length=10)
    supported_languages: Optional[list[str]] = None
    gentle_score: Optional[int] = Field(default=None, ge=0, le=100)
    proactive_score: Optional[int] = Field(default=None, ge=0, le=100)
    flirt_score: Optional[int] = Field(default=None, ge=0, le=100)
    humor_score: Optional[int] = Field(default=None, ge=0, le=100)
    emotional_depth_score: Optional[int] = Field(default=None, ge=0, le=100)
    boundary_score: Optional[int] = Field(default=None, ge=0, le=100)
    reply_length: Optional[str] = Field(default=None, min_length=1, max_length=10)
    tone: Optional[str] = Field(default=None, min_length=1, max_length=20)
    emoji_frequency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    prompt_en: Optional[str] = None
    prompt_es: Optional[str] = None
    prompt_fr: Optional[str] = None
    prompt_de: Optional[str] = None
    status: Optional[str] = Field(default=None, min_length=1, max_length=20)


def _validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a valid UUID"
        ) from exc


def _validate_character_payload(data: CharacterBase | CharacterUpdate) -> None:
    provided = getattr(data, "model_fields_set", set())
    non_nullable_update_fields = {
        "name",
        "default_language",
        "supported_languages",
        "gentle_score",
        "proactive_score",
        "flirt_score",
        "humor_score",
        "emotional_depth_score",
        "boundary_score",
        "reply_length",
        "tone",
        "emoji_frequency",
        "status",
    }
    for field in non_nullable_update_fields.intersection(provided):
        if getattr(data, field, None) is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")

    status_value = getattr(data, "status", None)
    if status_value is not None and status_value not in CHARACTER_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")

    reply_length = getattr(data, "reply_length", None)
    if reply_length is not None and reply_length not in REPLY_LENGTHS:
        raise HTTPException(status_code=422, detail="invalid reply_length")

    emoji_frequency = getattr(data, "emoji_frequency", None)
    if emoji_frequency is not None and emoji_frequency not in EMOJI_FREQUENCIES:
        raise HTTPException(status_code=422, detail="invalid emoji_frequency")

    supported = getattr(data, "supported_languages", None)
    if supported is not None:
        if not supported:
            raise HTTPException(
                status_code=422, detail="supported_languages cannot be empty"
            )
        if any(not isinstance(lang, str) or not lang.strip() for lang in supported):
            raise HTTPException(status_code=422, detail="invalid supported_languages")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


@router.get("")
async def list_characters(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM characters WHERE status='active' ORDER BY updated_at DESC"),
    )
    return [dict(r._mapping) for r in result.fetchall()]


@router.get("/stats")
async def character_stats(
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    status_rows = (
        await db.execute(
            text("SELECT status, COUNT(*)::int AS count FROM characters GROUP BY status")
        )
    ).fetchall()
    conversation_rows = (
        await db.execute(
            text(
                """
                SELECT character_id::text AS character_id, COUNT(*)::int AS count
                FROM conversations
                WHERE character_id IS NOT NULL
                GROUP BY character_id
                ORDER BY count DESC
                """
            )
        )
    ).fetchall()
    profile_rows = (
        await db.execute(
            text(
                """
                SELECT current_character_id::text AS character_id, COUNT(*)::int AS count
                FROM user_profiles
                WHERE current_character_id IS NOT NULL
                GROUP BY current_character_id
                ORDER BY count DESC
                """
            )
        )
    ).fetchall()

    by_status = {str(r[0] or "unknown"): int(r[1] or 0) for r in status_rows}
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "conversation_counts": [
            {"character_id": str(r[0]), "count": int(r[1] or 0)}
            for r in conversation_rows
        ],
        "profile_counts": [
            {"character_id": str(r[0]), "count": int(r[1] or 0)}
            for r in profile_rows
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_character(
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    _validate_character_payload(data)
    res = await db.execute(
        text(
            """
            INSERT INTO characters (
              id, name, age_feel, region, occupation, background,
              relationship_position, default_language, supported_languages,
              gentle_score, proactive_score, flirt_score, humor_score,
              emotional_depth_score, boundary_score, reply_length, tone,
              emoji_frequency, prompt_en, prompt_es, prompt_fr, prompt_de, status
            ) VALUES (
              :id, :name, :age_feel, :region, :occupation, :background,
              :relationship_position, :default_language,
              CAST(:supported_languages AS jsonb),
              :gentle_score, :proactive_score, :flirt_score, :humor_score,
              :emotional_depth_score, :boundary_score, :reply_length,
              :tone, :emoji_frequency, :prompt_en, :prompt_es, :prompt_fr,
              :prompt_de, :status
            )
            RETURNING *
            """
        ),
        {
            **data.model_dump(exclude={"supported_languages"}),
            "id": str(uuid.uuid4()),
            "supported_languages": json.dumps(
                data.supported_languages, ensure_ascii=False
            ),
        },
    )
    await db.commit()
    return _row_to_dict(res.fetchone())


@router.get("/{character_id}")
async def get_character(character_id: str, db: AsyncSession = Depends(get_db)):
    cid = _validate_uuid(character_id, "character_id")
    result = await db.execute(
        text("SELECT * FROM characters WHERE id=CAST(:id AS uuid)"),
        {"id": cid},
    )
    char = result.fetchone()
    if not char:
        raise HTTPException(404, "Character not found")
    return _row_to_dict(char)


@router.patch("/{character_id}")
async def update_character(
    character_id: str,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    cid = _validate_uuid(character_id, "character_id")
    _validate_character_payload(data)
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await get_character(character_id, db)

    if "supported_languages" in values:
        values["supported_languages"] = json.dumps(
            values["supported_languages"], ensure_ascii=False
        )

    casts = {"supported_languages": "CAST(:supported_languages AS jsonb)"}
    assignments = [f"{name} = {casts.get(name, ':' + name)}" for name in values]
    values["id"] = cid
    row = (
        await db.execute(
            text(
                f"""
                UPDATE characters
                SET {', '.join(assignments)}, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING *
                """
            ),
            values,
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await db.commit()
    return _row_to_dict(row)
