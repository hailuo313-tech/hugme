from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.character_recommender import recommend_character_for_onboarding


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(rows: list[Any]) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows
    return res


@pytest.mark.asyncio
async def test_recommend_character_prefers_language_and_chat_style_match():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            [
                _row(
                    {
                        "id": "00000000-0000-0000-0000-000000000401",
                        "name": "Nova",
                        "default_language": "en",
                        "supported_languages": ["en"],
                        "gentle_score": 50,
                        "proactive_score": 95,
                        "humor_score": 95,
                        "emotional_depth_score": 40,
                        "boundary_score": 50,
                        "tone": "playful",
                        "background": "music movies daily life",
                        "relationship_position": "casual friend",
                    }
                ),
                _row(
                    {
                        "id": "00000000-0000-0000-0000-000000000402",
                        "name": "Aria",
                        "default_language": "zh",
                        "supported_languages": ["zh"],
                        "gentle_score": 90,
                        "proactive_score": 30,
                        "humor_score": 30,
                        "emotional_depth_score": 90,
                        "boundary_score": 90,
                        "tone": "warm",
                        "background": "emotional companion",
                        "relationship_position": "close friend",
                    }
                ),
            ]
        )
    )

    recommendation = await recommend_character_for_onboarding(
        db,
        user_id="u1",
        profile={
            "language": "en-US",
            "chat_style": "casual",
            "interests": ["music"],
            "preferences": {"current_intent": "daily talk"},
        },
    )

    assert recommendation is not None
    assert recommendation.character_id == "00000000-0000-0000-0000-000000000401"
    assert recommendation.name == "Nova"
    assert "language_supported" in recommendation.reason
    assert "chat_style_tone_match" in recommendation.reason


@pytest.mark.asyncio
async def test_recommend_character_returns_none_without_active_rows():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result([]))

    recommendation = await recommend_character_for_onboarding(
        db,
        user_id="u1",
        profile={"language": "en", "chat_style": "warm"},
    )

    assert recommendation is None
