"""CUR-API-01：``GET /api/v1/admin/users/{user_id}`` 须 operator JWT。"""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator, router
from core.database import get_db


def _row(d: dict[str, Any]) -> MagicMock:
    r = MagicMock()
    r._mapping = d
    return r


def _result(rows: list[Any] | None = None, scalar: Any = None):
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = (
        rows[0] if rows else ((scalar,) if scalar is not None else None)
    )
    return res


def _db_with(results: list[Any]):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


def _build_app(db: Any | None = None, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    if db is not None:

        async def _fake_get_db() -> AsyncGenerator[Any, None]:
            yield db

        app.dependency_overrides[get_db] = _fake_get_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {
                "sub": "op-test",
                "username": "test_op",
                "role": "admin",
                "type": "operator",
            }

        app.dependency_overrides[require_operator] = _fake_operator

    return app


UID = "00000000-0000-0000-0000-000000000001"


def test_admin_users_route_registered():
    paths = [getattr(r, "path", "") for r in router.routes]
    assert any("/admin/users/" in p for p in paths), f"missing route, got {paths}"


def test_admin_user_401_without_token():
    app = _build_app(db=_db_with([]), with_auth=False)
    client = TestClient(app)
    r = client.get(f"/api/v1/admin/users/{UID}")
    assert r.status_code == 401, r.text


def test_admin_user_400_invalid_uuid():
    app = _build_app(
        db=_db_with([]),
    )
    client = TestClient(app)
    r = client.get(
        "/api/v1/admin/users/not-a-uuid",
        headers={"Authorization": "Bearer dummy"},
    )
    assert r.status_code == 400, r.text


def test_admin_user_404_not_found():
    app = _build_app(
        db=_db_with([_result(scalar=None)]),
    )
    client = TestClient(app)
    r = client.get(
        f"/api/v1/admin/users/{UID}",
        headers={"Authorization": "Bearer dummy"},
    )
    assert r.status_code == 404, r.text


def test_admin_user_200_happy_path():
    user = _row(
        {
            "id": UID,
            "nickname": "Aria fan",
            "channel": "telegram",
            "risk_level": "normal",
        }
    )
    profile = _row(
        {
            "user_id": UID,
            "loneliness_score": 42.5,
            "relationship_stage": "S1",
        }
    )
    mem = _row(
        {
            "id": str(uuid.uuid4()),
            "memory_type": "preference",
            "content": "喜欢猫",
            "importance_score": 8.0,
            "created_at": None,
        }
    )
    app = _build_app(
        db=_db_with(
            [
                _result([user]),
                _result([profile]),
                _result([mem]),
            ]
        ),
    )
    client = TestClient(app)
    r = client.get(
        f"/api/v1/admin/users/{UID}",
        headers={"Authorization": "Bearer dummy"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["nickname"] == "Aria fan"
    assert data["profile"]["loneliness_score"] == 42.5
    assert len(data["memories"]) == 1
    assert data["memories"][0]["content"] == "喜欢猫"
