from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass(frozen=True)
class CharacterRecommendation:
    character_id: str
    name: str
    score: float
    reason: str

    def to_response(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "match_score": round(self.score, 3),
            "reason": self.reason,
        }


_CHAT_STYLE_TONE_HINTS: dict[str, set[str]] = {
    "warm": {"warm", "calm"},
    "casual": {"playful", "casual", "warm"},
    "intellectual": {"thoughtful", "direct", "calm", "professional"},
}

_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("companionship", ("陪", "陪伴", "聊天", "说说话", "lonely", "talk", "companion")),
    ("emotional", ("难过", "焦虑", "压力", "心情", "sad", "anxious", "stress")),
    ("daily", ("生活", "日常", "电影", "音乐", "旅行", "游戏", "daily", "music", "movie")),
)


async def recommend_character_for_onboarding(
    db: Any,
    *,
    user_id: str,
    profile: dict[str, Any],
) -> CharacterRecommendation | None:
    """Recommend an active character from DB using onboarding profile signals.

    This intentionally avoids hardcoded character IDs. If no active character exists,
    the caller can decide whether to seed and fall back to a default character.
    """
    rows = await _load_active_characters(db)
    if not rows:
        return None

    language = _normalize_language(profile.get("language"))
    chat_style = str(profile.get("chat_style") or "warm").strip().lower()
    interests = set(_as_text_list(profile.get("interests")))
    prefs = _as_dict(profile.get("preferences"))
    intent = str(prefs.get("current_intent") or "").strip().lower()

    scored = [
        _score_character(
            row,
            language=language,
            chat_style=chat_style,
            interests=interests,
            intent=intent,
        )
        for row in rows
    ]
    scored.sort(key=lambda item: (item.score, item.name.lower()), reverse=True)
    best = scored[0]

    return CharacterRecommendation(
        character_id=best.character_id,
        name=best.name,
        score=best.score,
        reason=best.reason,
    )


async def _load_active_characters(db: Any) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id::text AS id, name, default_language, supported_languages,
                   gentle_score, proactive_score, humor_score,
                   emotional_depth_score, boundary_score, tone,
                   background, relationship_position
            FROM characters
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT 50
            """
        )
    )
    return [_row_to_dict(row) for row in (result.fetchall() or [])]


@dataclass(frozen=True)
class _ScoredCharacter:
    character_id: str
    name: str
    score: float
    reason: str


def _score_character(
    row: dict[str, Any],
    *,
    language: str,
    chat_style: str,
    interests: set[str],
    intent: str,
) -> _ScoredCharacter:
    score = 0.0
    reasons: list[str] = []

    supported_languages = {
        _normalize_language(lang) for lang in _as_text_list(row.get("supported_languages"))
    }
    default_language = _normalize_language(row.get("default_language"))
    if language and language in supported_languages:
        score += 4.0
        reasons.append("language_supported")
    elif language and language == default_language:
        score += 3.0
        reasons.append("default_language_match")

    tone = str(row.get("tone") or "").strip().lower()
    if tone in _CHAT_STYLE_TONE_HINTS.get(chat_style, set()):
        score += 3.0
        reasons.append("chat_style_tone_match")

    gentle = _as_score(row.get("gentle_score"))
    depth = _as_score(row.get("emotional_depth_score"))
    proactive = _as_score(row.get("proactive_score"))
    humor = _as_score(row.get("humor_score"))
    boundary = _as_score(row.get("boundary_score"))

    if chat_style == "warm":
        score += gentle * 0.02 + depth * 0.015 + boundary * 0.005
    elif chat_style == "casual":
        score += humor * 0.02 + proactive * 0.015 + gentle * 0.005
    elif chat_style == "intellectual":
        score += depth * 0.02 + boundary * 0.015 + gentle * 0.005
    else:
        score += gentle * 0.01 + depth * 0.01

    haystack = " ".join(
        str(row.get(key) or "").lower()
        for key in ("background", "relationship_position", "tone")
    )
    interest_hits = [interest for interest in interests if interest and interest.lower() in haystack]
    if interest_hits:
        score += min(2.0, len(interest_hits) * 0.75)
        reasons.append("interest_overlap")

    for label, keywords in _INTENT_KEYWORDS:
        if any(keyword in intent for keyword in keywords):
            if label in haystack or tone in {"warm", "calm", "thoughtful"}:
                score += 1.0
                reasons.append(f"intent_{label}")
            break

    if not reasons:
        reasons.append("active_character")

    return _ScoredCharacter(
        character_id=str(row.get("id")),
        name=str(row.get("name") or "Unknown"),
        score=round(score, 4),
        reason=",".join(reasons),
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    if getattr(row, "_mapping", None) is not None:
        return dict(row._mapping)
    return dict(row)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [raw]
    return []


def _normalize_language(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return "en"
    return raw.split("-")[0]


def _as_score(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 50.0
