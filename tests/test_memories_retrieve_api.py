"""D4-1 / D5-2：``POST /api/v1/users/{user_id}/memories/retrieve`` 须带 operator JWT。

最小 FastAPI 只挂 ``api.memories.router``；``dependency_overrides`` 注入假 DB；
``retriever_retrieve`` 用 monkeypatch 替换，避免真 embedding / SQL。
"""
from __future__ import annotations

import importlib
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.memories as memories_mod
from api.admin import require_operator
from core.database import get_db


def _mini_app(db: Any, *, with_auth: bool = True) -> FastAPI:
    importlib.reload(memories_mod)
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


@pytest.fixture
def fake_db() -> MagicMock:
    """AsyncSession.execute → 同步 ``fetchall()``，避免 MagicMock 产生未 await 的协程。"""
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


def test_retrieve_200_with_auth_and_stub_retriever(monkeypatch, fake_db: MagicMock):
    hit = MagicMock()
    hit.id = "m-1"
    hit.content = "喜欢爵士"
    hit.memory_type = "preference"
    hit.importance_score = 7.0
    hit.confidence_score = 1.0
    hit.emotion_tags = []
    hit.created_at = None
    hit.last_used_at = None
    hit.similarity = 0.91
    hit.final_score = 0.88

    rr = MagicMock()
    rr.embedding_used = True
    rr.fallback_reason = None
    rr.candidates_scanned = 4
    rr.latency_ms = 15.2
    rr.hits = [hit]

    fake_retrieve = AsyncMock(return_value=rr)
    monkeypatch.setattr(memories_mod, "retriever_retrieve", fake_retrieve)

    app = _mini_app(fake_db)
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/users/user-xyz/memories/retrieve",
            json={"query": "听什么", "k": 5},
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["embedding_used"] is True
    assert data["candidates_scanned"] == 4
    assert len(data["hits"]) == 1
    assert data["hits"][0]["content"] == "喜欢爵士"
    fake_retrieve.assert_awaited_once()
    assert fake_retrieve.await_args.kwargs["user_id"] == "user-xyz"
    assert fake_retrieve.await_args.kwargs["query_text"] == "听什么"
    assert fake_retrieve.await_args.kwargs["k_final"] == 5


def test_retrieve_401_without_bearer(fake_db: MagicMock):
    """无 JWT 须 401。显式 override：与 ``api.admin`` 的 HTTPBearer 行为互补，避免假 DB 误走检索。"""
    app = _mini_app(fake_db, with_auth=False)

    async def _deny_operator() -> dict:
        raise HTTPException(status_code=401, detail="Missing token")

    app.dependency_overrides[require_operator] = _deny_operator

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/users/u1/memories/retrieve",
            json={"query": "hello", "k": 3},
        )

    assert r.status_code == 401, r.text
