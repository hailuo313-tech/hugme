from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.open_api import router
from core.database import get_db

USER_ID = "00000000-0000-0000-0000-000000000101"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000102"
CHAR_ID = "00000000-0000-0000-0000-000000000201"
CONV_ID = "00000000-0000-0000-0000-000000000301"
MSG_ID = "00000000-0000-0000-0000-000000000401"
ASSISTANT_MSG_ID = "00000000-0000-0000-0000-000000000402"


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(*, rows: list[Any] | None = None, one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = one
    return res


def _app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/open")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db
    return app


def test_open_characters_returns_active_public_fields_only():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            rows=[
                _row(
                    {
                        "id": CHAR_ID,
                        "name": "Aria",
                        "age_feel": "24",
                        "region": "JP",
                        "occupation": "designer",
                        "background": "warm companion",
                        "relationship_position": "friend",
                        "default_language": "zh",
                        "supported_languages": ["zh", "en"],
                        "tone": "warm",
                        "reply_length": "medium",
                        "prompt_en": "internal",
                    }
                )
            ]
        )
    )
    client = TestClient(_app(db))

    r = client.get("/api/v1/open/characters")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data[0]["name"] == "Aria"
    assert data[0]["supported_languages"] == ["zh", "en"]
    assert "prompt_en" not in data[0]
    assert "gentle_score" not in data[0]
    assert "status='active'" in str(db.execute.await_args.args[0])


def test_open_profile_returns_safe_fields_and_requires_user_match():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row(
                {
                    "user_id": USER_ID,
                    "nickname": "小海",
                    "language": "zh",
                    "timezone": "Asia/Shanghai",
                    "relationship_stage": "S1",
                    "preferences": {
                        "onboarding_step": 6,
                        "current_intent": "chat",
                        "unsafe_internal": "hide",
                    },
                    "interests": ["music"],
                    "chat_style": "warm",
                    "character_id": CHAR_ID,
                    "character_name": "Aria",
                    "risk_score": 99,
                    "dependency_score": 88,
                }
            )
        )
    )
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/open/users/{USER_ID}/profile",
        headers={"X-User-Id": USER_ID},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user_id"] == USER_ID
    assert data["onboarding"] == {"step": 6, "completed": True}
    assert data["current_character"] == {"id": CHAR_ID, "name": "Aria"}
    assert data["preferences"] == {
        "chat_style": "warm",
        "interests": ["music"],
        "current_intent": "chat",
    }
    assert "risk_score" not in data
    assert "dependency_score" not in data


def test_open_profile_rejects_user_mismatch_before_db():
    db = MagicMock()
    db.execute = AsyncMock()
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/open/users/{USER_ID}/profile",
        headers={"X-User-Id": OTHER_USER_ID},
    )

    assert r.status_code == 403
    db.execute.assert_not_awaited()


def test_open_profile_user_not_found():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/open/users/{USER_ID}/profile",
        headers={"X-User-Id": USER_ID},
    )

    assert r.status_code == 404


def test_create_open_conversation_reuses_ai_active_conversation():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=_row({"id": USER_ID, "status": "active"})),
            _result(one=_row({"id": CHAR_ID})),
            _result(one=_row({"id": CONV_ID, "state": "AI_ACTIVE"})),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/open/conversations",
        headers={"X-User-Id": USER_ID},
        json={"user_id": USER_ID, "character_id": CHAR_ID, "channel": "web"},
    )

    assert r.status_code == 201, r.text
    assert r.json() == {
        "conversation_id": CONV_ID,
        "user_id": USER_ID,
        "character_id": CHAR_ID,
        "state": "AI_ACTIVE",
    }
    db.commit.assert_not_awaited()


def test_create_open_conversation_rejects_inactive_character():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=_row({"id": USER_ID, "status": "active"})),
            _result(one=None),
        ]
    )
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/open/conversations",
        headers={"X-User-Id": USER_ID},
        json={"user_id": USER_ID, "character_id": CHAR_ID},
    )

    assert r.status_code == 404


def test_send_open_message_uses_orchestrator(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row(
                {
                    "id": CONV_ID,
                    "user_id": USER_ID,
                    "state": "AI_ACTIVE",
                    "is_minor_suspected": False,
                    "user_status": "active",
                }
            )
        )
    )
    client = TestClient(_app(db))

    async def _redis():
        return MagicMock()

    async def _push(*args, **kwargs):
        return None

    async def _memory(*args, **kwargs):
        return None

    async def _reply(*args, **kwargs):
        return "AI reply"

    persist = AsyncMock(side_effect=[MSG_ID, ASSISTANT_MSG_ID])
    monkeypatch.setattr("api.open_api.get_redis", _redis)
    monkeypatch.setattr("api.open_api._push_context", _push)
    monkeypatch.setattr("api.open_api.maybe_write_memory", _memory)
    monkeypatch.setattr("api.open_api.generate_reply", _reply)
    monkeypatch.setattr("api.open_api._persist_message", persist)

    r = client.post(
        f"/api/v1/open/conversations/{CONV_ID}/messages",
        headers={"X-User-Id": USER_ID},
        json={"user_id": USER_ID, "content": "今天有点累", "content_type": "text"},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["message_id"] == MSG_ID
    assert data["assistant_message"]["id"] == ASSISTANT_MSG_ID
    assert data["assistant_message"]["content"] == "AI reply"
    assert data["safety"] == {"blocked": False, "reason": None}
    assert persist.await_count == 2


def test_list_open_messages_paginates_and_hides_internal_fields():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=_row({"user_id": USER_ID})),
            _result(
                rows=[
                    _row(
                        {
                            "id": MSG_ID,
                            "sender_type": "user",
                            "content": "hi",
                            "content_type": "text",
                            "created_at": datetime(2026, 5, 16, 1, 2, 3),
                            "safety_result": {"blocked": False},
                            "model_name": "internal-model",
                        }
                    )
                ]
            ),
        ]
    )
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/open/conversations/{CONV_ID}/messages?limit=50",
        headers={"X-User-Id": USER_ID},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["items"][0]["content"] == "hi"
    assert "safety_result" not in data["items"][0]
    assert "model_name" not in data["items"][0]
    assert data["has_more"] is False


def test_list_open_messages_rejects_other_user():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=_row({"user_id": OTHER_USER_ID})))
    client = TestClient(_app(db))

    r = client.get(
        f"/api/v1/open/conversations/{CONV_ID}/messages",
        headers={"X-User-Id": USER_ID},
    )

    assert r.status_code == 403
