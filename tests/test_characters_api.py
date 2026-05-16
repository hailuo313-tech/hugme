"""P2 characters POST/PATCH/stats API."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.characters import router
from core.database import get_db

CHAR_ID = "00000000-0000-0000-0000-000000000301"


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(*, rows: list[Any] | None = None, one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = one
    return res


def _app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/characters")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": "op", "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_list_characters_public_active_only_default():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(rows=[_row({"id": CHAR_ID, "name": "Aria"})])
    )
    client = TestClient(_app(db, with_auth=False))

    r = client.get("/api/v1/characters")

    assert r.status_code == 200, r.text
    assert r.json()[0]["name"] == "Aria"
    assert "status='active'" in str(db.execute.await_args.args[0])


def test_create_character_requires_operator():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.post("/api/v1/characters", json={"name": "Aria"})

    assert r.status_code == 401


def test_create_character_inserts_supported_languages_jsonb():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row({"id": CHAR_ID, "name": "Nova", "status": "draft"})
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/characters",
        json={
            "name": "Nova",
            "supported_languages": ["en", "es"],
            "status": "draft",
            "gentle_score": 70,
            "reply_length": "medium",
            "emoji_frequency": "low",
        },
    )

    assert r.status_code == 201, r.text
    params = db.execute.await_args.args[1]
    assert params["name"] == "Nova"
    assert params["supported_languages"] == '["en", "es"]'
    db.commit.assert_awaited_once()


def test_patch_character_updates_only_provided_fields():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row({"id": CHAR_ID, "name": "Nova", "status": "active"})
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.patch(
        f"/api/v1/characters/{CHAR_ID}",
        json={"status": "active", "tone": "playful"},
    )

    assert r.status_code == 200, r.text
    sql = str(db.execute.await_args.args[0])
    assert "status = :status" in sql
    assert "tone = :tone" in sql
    assert "updated_at = NOW()" in sql
    db.commit.assert_awaited_once()


def test_patch_character_validates_scores_and_enums():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.patch(f"/api/v1/characters/{CHAR_ID}", json={"gentle_score": 101})
    assert r.status_code == 422

    r = client.patch(f"/api/v1/characters/{CHAR_ID}", json={"status": "banana"})
    assert r.status_code == 422

    r = client.patch(f"/api/v1/characters/{CHAR_ID}", json={"name": None})
    assert r.status_code == 422

    r = client.patch(
        f"/api/v1/characters/{CHAR_ID}", json={"supported_languages": None}
    )
    assert r.status_code == 422


def test_character_stats_requires_operator():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.get("/api/v1/characters/stats")

    assert r.status_code == 401


def test_character_stats_returns_counts():
    status_rows = [("active", 2), ("draft", 1)]
    conversation_rows = [(CHAR_ID, 5)]
    profile_rows = [(CHAR_ID, 3)]
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(rows=status_rows),
            _result(rows=conversation_rows),
            _result(rows=profile_rows),
        ]
    )
    client = TestClient(_app(db))

    r = client.get("/api/v1/characters/stats")

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 3
    assert data["by_status"] == {"active": 2, "draft": 1}
    assert data["conversation_counts"] == [{"character_id": CHAR_ID, "count": 5}]
    assert data["profile_counts"] == [{"character_id": CHAR_ID, "count": 3}]
