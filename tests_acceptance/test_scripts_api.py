"""P2 scripts library CRUD + suggest API."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.scripts import router
from core.database import get_db

SCRIPT_ID = "00000000-0000-0000-0000-000000000101"
CHAR_ID = "00000000-0000-0000-0000-000000000202"


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
    app.include_router(router, prefix="/api/v1/scripts")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:
        async def _fake_operator() -> dict:
            return {"sub": "op", "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_scripts_requires_operator_token():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.get("/api/v1/scripts")

    assert r.status_code == 401


def test_list_scripts_filters():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(rows=[_row({"id": SCRIPT_ID, "content": "hello"})])
    )
    client = TestClient(_app(db))

    r = client.get(
        "/api/v1/scripts",
        params={
            "language": "en",
            "relationship_stage": "S2",
            "script_type": "reply",
            "review_status": "approved",
            "character_id": CHAR_ID,
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["content"] == "hello"
    params = db.execute.await_args.args[1]
    assert params["language"] == "en"
    assert params["character_id"] == CHAR_ID


def test_create_script_inserts_jsonb_and_commits():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row(
                {"id": SCRIPT_ID, "content": "Hi there", "review_status": "draft"}
            )
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/scripts",
        json={
            "character_id": CHAR_ID,
            "language": "en",
            "relationship_stage": "S2",
            "emotion_state": "lonely",
            "script_type": "reply",
            "content": "Hi there",
            "review_status": "draft",
            "forbidden_scenarios": ["minor"],
        },
    )

    assert r.status_code == 201, r.text
    params = db.execute.await_args.args[1]
    assert params["character_id"] == CHAR_ID
    assert params["forbidden_scenarios"] == '["minor"]'
    db.commit.assert_awaited_once()


def test_update_script_patches_only_provided_fields():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_row(
                {"id": SCRIPT_ID, "content": "Updated", "review_status": "approved"}
            )
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.patch(
        f"/api/v1/scripts/{SCRIPT_ID}",
        json={"content": "Updated", "review_status": "approved"},
    )

    assert r.status_code == 200, r.text
    sql = str(db.execute.await_args.args[0])
    assert "content = :content" in sql
    assert "review_status = :review_status" in sql
    assert "updated_at = NOW()" in sql
    db.commit.assert_awaited_once()


def test_delete_script_returns_deleted():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=(SCRIPT_ID,)))
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.delete(f"/api/v1/scripts/{SCRIPT_ID}")

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "deleted", "script_id": SCRIPT_ID}
    db.commit.assert_awaited_once()


def test_suggest_scripts_uses_approved_filters_and_score():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            rows=[
                _row(
                    {
                        "id": SCRIPT_ID,
                        "content": "Suggested",
                        "match_score": 90,
                    }
                )
            ]
        )
    )
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/scripts/suggest",
        json={
            "character_id": CHAR_ID,
            "language": "en",
            "relationship_stage": "S3",
            "emotion_state": "lonely",
            "loneliness_score": 80,
            "script_type": "reply",
            "risk_level": "low",
            "conversion_goal": "retain",
            "limit": 3,
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["match_score"] == 90
    sql = str(db.execute.await_args.args[0])
    assert "review_status = 'approved'" in sql
    assert "match_score" in sql
    params = db.execute.await_args.args[1]
    assert params["relationship_stage"] == "S3"
    assert params["loneliness_score"] == 80
    assert params["limit"] == 3
