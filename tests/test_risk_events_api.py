"""V001-P0-3：risk_events API 写库与列表。"""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.users import router
from core.database import get_db

USER_ID = "00000000-0000-0000-0000-000000000099"


def _row(d: dict) -> MagicMock:
    r = MagicMock()
    r._mapping = d
    return r


def _mini_app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/users")

    async def _fake_get_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_get_db
    return app


def test_create_risk_event_persists():
    db = MagicMock()
    user_row = _row({"id": USER_ID})
    db.execute = AsyncMock(return_value=MagicMock(fetchone=lambda: user_row))
    db.commit = AsyncMock()

    app = _mini_app(db)
    with TestClient(app) as client:
        r = client.post(
            f"/api/v1/users/{USER_ID}/risk-events",
            json={
                "risk_type": "policy_flag",
                "severity": "P1",
                "description": "test",
            },
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "created"
    assert uuid.UUID(data["risk_event_id"])
    assert db.execute.await_count >= 3
    db.commit.assert_awaited_once()


def test_list_risk_events():
    item = _row(
        {
            "id": str(uuid.uuid4()),
            "user_id": USER_ID,
            "risk_type": "crisis",
            "severity": "P0",
            "trigger_message_id": None,
            "description": "x",
            "handled_by": None,
            "handled_at": None,
            "resolution": None,
            "created_at": None,
        }
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: [item]))

    app = _mini_app(db)
    with TestClient(app) as client:
        r = client.get(f"/api/v1/users/{USER_ID}/risk-events")
    assert r.status_code == 200
    assert r.json()["total"] == 1
