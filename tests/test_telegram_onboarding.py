from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from api import telegram


@pytest.mark.asyncio
async def test_telegram_onboarding_step5_assigns_character_with_profile_dict(monkeypatch):
    db = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = ("Alex",)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def fake_get_profile_prefs(db_arg: Any, user_id: str) -> dict[str, Any]:
        assert db_arg is db
        assert user_id == "user-1"
        return {"onboarding_step": 4, "onboarding_language": "en"}

    async def fake_load_profile(db_arg: Any, user_id: str) -> dict[str, Any]:
        assert db_arg is db
        assert user_id == "user-1"
        return {
            "language": "en",
            "chat_style": "casual",
            "interests": ["music"],
            "preferences": {"current_intent": "daily talk"},
        }

    async def fake_assign_character(
        db_arg: Any,
        user_id: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        assert db_arg is db
        assert user_id == "user-1"
        assert isinstance(profile, dict)
        assert profile["chat_style"] == "casual"
        assert profile["preferences"]["current_intent"] == "daily talk"
        return {
            "character_id": "00000000-0000-0000-0000-000000000501",
            "name": "Nova",
            "match_score": 9.5,
            "reason": "language_supported",
        }

    sent_messages: list[str] = []

    async def fake_send_tg(chat_id: int, text_content: str, trace_id: str) -> int:
        sent_messages.append(text_content)
        return 123

    monkeypatch.setattr(telegram, "_get_profile_prefs", fake_get_profile_prefs)
    monkeypatch.setattr(telegram, "_load_onboarding_profile", fake_load_profile)
    monkeypatch.setattr(telegram, "_assign_character", fake_assign_character)
    monkeypatch.setattr(telegram, "_send_tg", fake_send_tg)

    reply = await telegram._handle_onboarding(
        db,
        redis=MagicMock(),
        user_id="user-1",
        conv_id="conv-1",
        chat_id=42,
        text_content="daily talk",
        trace_id="trace-1",
    )

    assert reply == "Setup complete. You can start the conversation now."
    assert sent_messages == [reply]
    db.commit.assert_awaited()
