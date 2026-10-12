"""P2 operator quality score API."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.operator_quality import router
from core.database import get_db

QUALITY_ID = "00000000-0000-0000-0000-000000000501"
HANDOFF_ID = "00000000-0000-0000-0000-000000000502"
OPERATOR_ID = "00000000-0000-0000-0000-000000000503"
REVIEWER_ID = "00000000-0000-0000-0000-000000000504"
CONVERSATION_ID = "00000000-0000-0000-0000-000000000505"
USER_ID = "00000000-0000-0000-0000-000000000506"
MESSAGE_ID = "00000000-0000-0000-0000-000000000507"


def _row(data: dict[str, Any]) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    return row


def _result(*, rows: list[Any] | None = None, one: Any | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = one
    return res


def _quality_row(**overrides: Any) -> MagicMock:
    data = {
        "id": QUALITY_ID,
        "handoff_task_id": HANDOFF_ID,
        "operator_id": OPERATOR_ID,
        "reviewer_operator_id": REVIEWER_ID,
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
        "message_id": MESSAGE_ID,
        "overall_score": 85,
        "empathy_score": 90,
        "accuracy_score": 80,
        "safety_score": 95,
        "timeliness_score": 75,
        "result": "passed",
        "issue_tags": [],
        "review_notes": "Handled well.",
        "created_at": "2026-05-16T00:00:00",
        "updated_at": "2026-05-16T00:00:00",
    }
    data.update(overrides)
    return _row(data)


def _app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operator-quality")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": REVIEWER_ID, "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_operator_quality_requires_operator_token():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.get("/api/v1/operator-quality")

    assert r.status_code == 401


def test_create_quality_score_happy_path():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=_quality_row()))
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/operator-quality",
        json={
            "operator_id": OPERATOR_ID,
            "overall_score": 85,
            "empathy_score": 90,
            "accuracy_score": 80,
            "safety_score": 95,
            "timeliness_score": 75,
            "result": "passed",
            "issue_tags": [],
            "review_notes": "Handled well.",
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == QUALITY_ID
    assert body["overall_score"] == 85
    assert body["reviewer_operator_id"] == REVIEWER_ID
    params = db.execute.await_args.args[1]
    assert params["operator_id"] == OPERATOR_ID
    assert params["reviewer_operator_id"] == REVIEWER_ID
    db.commit.assert_awaited_once()


def test_create_quality_score_rejects_invalid_score_result_and_tag():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/operator-quality",
        json={"operator_id": OPERATOR_ID, "overall_score": 101},
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/operator-quality",
        json={
            "operator_id": OPERATOR_ID,
            "overall_score": 80,
            "result": "banana",
        },
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/operator-quality",
        json={
            "operator_id": OPERATOR_ID,
            "overall_score": 80,
            "issue_tags": ["not_allowed"],
        },
    )
    assert r.status_code == 422


def test_create_quality_score_validates_handoff_exists():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.post(
        "/api/v1/operator-quality",
        json={
            "handoff_task_id": HANDOFF_ID,
            "operator_id": OPERATOR_ID,
            "overall_score": 85,
        },
    )

    assert r.status_code == 404
    assert r.json()["detail"] == "handoff_task not found"


def test_list_quality_scores_filters():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(rows=[_quality_row()]))
    client = TestClient(_app(db))

    r = client.get(
        "/api/v1/operator-quality",
        params={
            "operator_id": OPERATOR_ID,
            "handoff_task_id": HANDOFF_ID,
            "conversation_id": CONVERSATION_ID,
            "user_id": USER_ID,
            "result": "passed",
            "limit": 25,
            "offset": 5,
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["id"] == QUALITY_ID
    params = db.execute.await_args.args[1]
    assert params["operator_id"] == OPERATOR_ID
    assert params["handoff_task_id"] == HANDOFF_ID
    assert params["conversation_id"] == CONVERSATION_ID
    assert params["user_id"] == USER_ID
    assert params["result"] == "passed"
    assert params["limit"] == 25
    assert params["offset"] == 5


def test_get_quality_score_404_when_missing():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.get(f"/api/v1/operator-quality/{QUALITY_ID}")

    assert r.status_code == 404


def test_patch_quality_score_updates_fields_and_reviewer():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_result(
            one=_quality_row(
                overall_score=90,
                empathy_score=95,
                issue_tags=["tone_issue"],
                review_notes="Updated by smoke.",
            )
        )
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.patch(
        f"/api/v1/operator-quality/{QUALITY_ID}",
        json={
            "overall_score": 90,
            "empathy_score": 95,
            "result": "passed",
            "issue_tags": ["tone_issue"],
            "review_notes": "Updated by smoke.",
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["overall_score"] == 90
    sql = str(db.execute.await_args.args[0])
    assert "overall_score = :overall_score" in sql
    assert "reviewer_operator_id = CAST(:reviewer_operator_id AS uuid)" in sql
    assert "updated_at = NOW()" in sql
    params = db.execute.await_args.args[1]
    assert params["reviewer_operator_id"] == REVIEWER_ID
    assert params["issue_tags"] == '["tone_issue"]'
    db.commit.assert_awaited_once()


def test_patch_quality_score_404_when_missing():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.patch(
        f"/api/v1/operator-quality/{QUALITY_ID}",
        json={"overall_score": 90},
    )

    assert r.status_code == 404
