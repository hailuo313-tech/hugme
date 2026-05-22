from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import _verify_jwt, require_operator
from core.config import settings
from core.database import get_db

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


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
    profile_details: dict[str, Any] = Field(default_factory=dict)
    default_language: str = Field(default="en", min_length=1, max_length=10)
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    gentle_score: int = Field(default=50, ge=0, le=100)
    proactive_score: int = Field(default=50, ge=0, le=100)
    flirt_score: int = Field(default=30, ge=0, le=100)
    humor_score: int = Field(default=40, ge=0, le=100)
    emotional_depth_score: int = Field(default=60, ge=0, le=100)
    boundary_score: int = Field(default=70, ge=0, le=100)
    reply_length: str = Field(default="medium", min_length=1, max_length=10)
    tone: str = Field(default="warm", min_length=1, max_length=100)
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
    profile_details: Optional[dict[str, Any]] = None
    default_language: Optional[str] = Field(default=None, min_length=1, max_length=10)
    supported_languages: Optional[list[str]] = None
    gentle_score: Optional[int] = Field(default=None, ge=0, le=100)
    proactive_score: Optional[int] = Field(default=None, ge=0, le=100)
    flirt_score: Optional[int] = Field(default=None, ge=0, le=100)
    humor_score: Optional[int] = Field(default=None, ge=0, le=100)
    emotional_depth_score: Optional[int] = Field(default=None, ge=0, le=100)
    boundary_score: Optional[int] = Field(default=None, ge=0, le=100)
    reply_length: Optional[str] = Field(default=None, min_length=1, max_length=10)
    tone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    emoji_frequency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    prompt_en: Optional[str] = None
    prompt_es: Optional[str] = None
    prompt_fr: Optional[str] = None
    prompt_de: Optional[str] = None
    status: Optional[str] = Field(default=None, min_length=1, max_length=20)


class UserCharacterAssignment(BaseModel):
    character_id: str


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

    profile_details = getattr(data, "profile_details", None)
    if profile_details is not None and not isinstance(profile_details, dict):
        raise HTTPException(status_code=422, detail="profile_details must be an object")


def _derive_legacy_fields(values: dict[str, Any]) -> dict[str, Any]:
    details = values.get("profile_details")
    if not isinstance(details, dict):
        return values

    if not values.get("age_feel") and details.get("age"):
        values["age_feel"] = str(details["age"])
    if not values.get("region"):
        region_parts = [
            str(details[key]).strip()
            for key in ("birthplace", "current_city")
            if details.get(key)
        ]
        if region_parts:
            values["region"] = " / ".join(region_parts)
    if not values.get("occupation") and details.get("occupation"):
        values["occupation"] = str(details["occupation"])
    if not values.get("relationship_position") and details.get("relationship_status"):
        values["relationship_position"] = str(details["relationship_status"])
    if not values.get("background"):
        background_parts = [
            str(details[key]).strip()
            for key in ("family_origin", "childhood_background", "life_goal")
            if details.get(key)
        ]
        if background_parts:
            values["background"] = "；".join(background_parts)
    return values


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


@router.get("")
async def list_characters(
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
):
    if include_inactive:
        payload = (
            _verify_jwt(creds.credentials, settings.SECRET_KEY)
            if creds and creds.credentials
            else None
        )
        if not payload or payload.get("type") != "operator":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid operator token",
            )
        result = await db.execute(
            text("SELECT * FROM characters ORDER BY updated_at DESC"),
        )
        return [dict(r._mapping) for r in result.fetchall()]

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


@router.patch("/users/{user_id}/character")
async def assign_user_character(
    user_id: str,
    data: UserCharacterAssignment,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    uid = _validate_uuid(user_id, "user_id")
    cid = _validate_uuid(data.character_id, "character_id")

    user_row = (
        await db.execute(text("SELECT id FROM users WHERE id=CAST(:uid AS uuid)"), {"uid": uid})
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="user not found")

    character_row = (
        await db.execute(
            text(
                """
                SELECT id, name, age_feel, region, occupation
                FROM characters
                WHERE id = CAST(:cid AS uuid) AND status = 'active'
                """
            ),
            {"cid": cid},
        )
    ).fetchone()
    if not character_row:
        raise HTTPException(status_code=404, detail="active character not found")

    await db.execute(
        text(
            """
            INSERT INTO user_profiles (user_id, current_character_id, updated_at)
            VALUES (CAST(:uid AS uuid), CAST(:cid AS uuid), NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET current_character_id = EXCLUDED.current_character_id,
                updated_at = NOW()
            """
        ),
        {"uid": uid, "cid": cid},
    )
    conv_result = await db.execute(
        text(
            """
            UPDATE conversations
            SET character_id = CAST(:cid AS uuid),
                updated_at = NOW()
            WHERE user_id = CAST(:uid AS uuid)
              AND state = 'AI_ACTIVE'
            """
        ),
        {"uid": uid, "cid": cid},
    )
    await db.commit()

    return {
        "user_id": uid,
        "character": _row_to_dict(character_row),
        "updated_conversations": getattr(conv_result, "rowcount", None),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_character(
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    _validate_character_payload(data)
    values = _derive_legacy_fields(data.model_dump())
    res = await db.execute(
        text(
            """
            INSERT INTO characters (
              id, name, age_feel, region, occupation, background,
              relationship_position, profile_details, default_language, supported_languages,
              gentle_score, proactive_score, flirt_score, humor_score,
              emotional_depth_score, boundary_score, reply_length, tone,
              emoji_frequency, prompt_en, prompt_es, prompt_fr, prompt_de, status
            ) VALUES (
              :id, :name, :age_feel, :region, :occupation, :background,
              :relationship_position, CAST(:profile_details AS jsonb), :default_language,
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
            **{
                k: v
                for k, v in values.items()
                if k not in {"supported_languages", "profile_details"}
            },
            "id": str(uuid.uuid4()),
            "supported_languages": json.dumps(
                values["supported_languages"], ensure_ascii=False
            ),
            "profile_details": json.dumps(
                values.get("profile_details") or {}, ensure_ascii=False
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
    values = _derive_legacy_fields(data.model_dump(exclude_unset=True))
    if not values:
        return await get_character(character_id, db)

    if "supported_languages" in values:
        values["supported_languages"] = json.dumps(
            values["supported_languages"], ensure_ascii=False
        )
    if "profile_details" in values:
        values["profile_details"] = json.dumps(
            values["profile_details"] or {}, ensure_ascii=False
        )

    casts = {
        "supported_languages": "CAST(:supported_languages AS jsonb)",
        "profile_details": "CAST(:profile_details AS jsonb)",
    }
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
