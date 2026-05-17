from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api import onboarding
from services.character_recommender import CharacterRecommendation


@pytest.mark.asyncio
async def test_assign_character_uses_recommender_not_default_id(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()

    async def fake_recommend(db_arg: Any, *, user_id: str, profile: dict[str, Any]):
        assert db_arg is db
        assert user_id == "user-1"
        assert profile["chat_style"] == "casual"
        return CharacterRecommendation(
            character_id="00000000-0000-0000-0000-000000000501",
            name="Nova",
            score=9.5,
            reason="language_supported,chat_style_tone_match",
        )

    monkeypatch.setattr(onboarding, "recommend_character_for_onboarding", fake_recommend)

    assigned = await onboarding._assign_character(
        db,
        "user-1",
        {"language": "en", "chat_style": "casual"},
    )

    assert assigned["character_id"] == "00000000-0000-0000-0000-000000000501"
    assert assigned["name"] == "Nova"
    assert assigned["match_score"] == 9.5
    params = db.execute.await_args.args[1]
    assert params["cid"] == "00000000-0000-0000-0000-000000000501"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_assigned_character_reads_character_name_from_db():
    row = MagicMock()
    row._mapping = {
        "character_id": "00000000-0000-0000-0000-000000000502",
        "name": "Mira",
    }
    result = MagicMock()
    result.fetchone.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    assigned = await onboarding._get_assigned_character(db, "user-1")

    assert assigned == {
        "character_id": "00000000-0000-0000-0000-000000000502",
        "name": "Mira",
    }
    sql = str(db.execute.await_args.args[0])
    assert "LEFT JOIN characters" in sql
