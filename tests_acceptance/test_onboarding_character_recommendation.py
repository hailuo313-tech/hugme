from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api import onboarding
from services.character_recommender import CharacterRecommendation


DISALLOWED_COPY_TERMS = (
    "🌸",
    "✨",
    "😊",
    "💬",
    "🎉",
    "温柔陪伴",
    "专属陪伴",
    "比如",
    "快好啦",
    "太棒了",
    "我记住了",
    "说说话",
    "陪伴",
)


def _fixed_onboarding_replies() -> list[str]:
    replies: list[str] = []
    for language in ("zh", "en"):
        for step in range(1, onboarding.ONBOARDING_STEPS + 1):
            reply = onboarding._build_next_question(step, "Alex", language)
            assert reply is not None
            replies.append(reply)
        replies.append(onboarding._build_completion_message("Alex", language))
    return replies


def test_onboarding_fixed_replies_are_direct_copy():
    replies = _fixed_onboarding_replies()

    for reply in replies:
        assert not re.search(r"[🌀-🫿]", reply)
        assert not re.search(r"[()（）*＊]", reply)
        for term in DISALLOWED_COPY_TERMS:
            assert term not in reply


def test_onboarding_uses_english_for_english_input():
    language = onboarding._detect_onboarding_language("My name is Alex")

    assert language == "en"
    assert onboarding._build_next_question(1, language=language) == (
        "Please tell me what I should call you."
    )
    next_question = onboarding._build_next_question(2, "Alex", language)
    assert next_question is not None
    assert next_question.startswith("Alex, please tell me")
    assert not re.search(r"[一-鿿]", next_question)



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
async def test_assign_character_normalizes_legacy_string_profile(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()

    async def fake_recommend(db_arg: Any, *, user_id: str, profile: dict[str, Any]):
        assert isinstance(profile, dict)
        assert profile == {"chat_style": "casual"}
        return CharacterRecommendation(
            character_id="00000000-0000-0000-0000-000000000503",
            name="Kai",
            score=7.0,
            reason="legacy_profile_normalized",
        )

    monkeypatch.setattr(onboarding, "recommend_character_for_onboarding", fake_recommend)

    assigned = await onboarding._assign_character(db, "user-1", "casual")

    assert assigned["character_id"] == "00000000-0000-0000-0000-000000000503"
    assert assigned["reason"] == "legacy_profile_normalized"


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
