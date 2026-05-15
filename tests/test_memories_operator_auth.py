"""CUR-API-01: memories CRUD routes require operator JWT."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.memories as memories_mod
from api.admin import require_operator
from core.database import get_db


def _fake_db(rows: list | None = None) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    db.execute = AsyncMock(return_value=result)
    return db


def _mini_app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(memories_mod.router, prefix="/api/v1")

    async def _fake_get_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_get_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": "op-1", "username": "t", "role": "admin", "type": "operator"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_get_memories_401_without_bearer():
    app = _mini_app(_fake_db(), with_auth=False)

    async def _deny_operator() -> dict:
        raise HTTPException(status_code=401, detail="Missing token")

    app.dependency_overrides[require_operator] = _deny_operator

    with TestClient(app) as client:
        r = client.get("/api/v1/users/u1/memories")
    assert r.status_code == 401, r.text


def test_get_memories_200_with_bearer():
    row = MagicMock()
    row._mapping = {
        "id": "m1",
        "user_id": "u1",
        "memory_type": "fact",
        "content": "hello",
        "is_active": True,
    }
    app = _mini_app(_fake_db([row]))
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/users/u1/memories",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 200, r.text
    assert r.json()[0]["content"] == "hello"
