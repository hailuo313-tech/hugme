"""D5-2 单测：``GET /api/v1/admin/conversations`` 列表 + 详情。

策略：mount 一个最小 FastAPI，仅挂 ``api.admin.router``；通过
``dependency_overrides`` 注入假 ``AsyncSession`` 与假 ``require_operator``。
不依赖真 DB / Redis / Postgres。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator, router
from core.database import get_db


# ── helpers ─────────────────────────────────────────────────────────


def _row(d: dict[str, Any]) -> MagicMock:
    """Mock 一个 SQLAlchemy Row：``row._mapping`` 是个 dict。"""
    r = MagicMock()
    r._mapping = d
    return r


def _result(rows: list[Any] | None = None, scalar: Any = None):
    """Mock ``await db.execute(...)`` 的返回值。"""
    res = MagicMock()
    res.fetchall.return_value = rows or []
    res.fetchone.return_value = (
        rows[0]
        if rows
        else ((scalar,) if scalar is not None else None)
    )
    return res


def _db_with(results: list[Any]):
    """按队列顺序返回 mock result，供 ``db.execute()`` 多次 await。"""
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
            return {"sub": "op-test", "username": "test_op", "role": "admin", "type": "operator"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


# ── auth ────────────────────────────────────────────────────────────


def test_list_returns_401_without_token():
    """没带 Bearer → 401。"""
    app = _build_app(db=_db_with([]), with_auth=False)  # 不覆盖 require_operator
    client = TestClient(app)
    r = client.get("/api/v1/admin/conversations")
    assert r.status_code == 401, r.text


def test_detail_returns_401_without_token():
    app = _build_app(db=_db_with([]), with_auth=False)
    client = TestClient(app)
    r = client.get("/api/v1/admin/conversations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401, r.text


# ── list happy path ────────────────────────────────────────────────


def test_list_happy_path_with_items():
    """两次 execute：先 COUNT(*)=2，再返回 2 行。"""
    row1 = _row({
        "conversation_id": "c1",
        "state": "AI_ACTIVE",
        "handoff_count": 0,
        "channel": "telegram",
        "last_message_at": None,
        "created_at": None,
        "assigned_operator_id": None,
        "user_id": "u1",
        "nickname": "Alice",
        "external_id": "tg_111",
        "user_channel": "telegram",
        "risk_level": "normal",
        "user_status": "active",
        "loneliness_score": 42.5,
        "vip_level": 0,
        "relationship_stage": "S0",
        "character_id": "ch1",
        "character_name": "Aria",
    })
    row2 = _row({**row1._mapping, "conversation_id": "c2", "nickname": "Bob"})

    db = _db_with([_result(scalar=2), _result(rows=[row1, row2])])
    client = TestClient(_build_app(db=db))

    r = client.get("/api/v1/admin/conversations?page=1&page_size=10")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert len(data["items"]) == 2
    assert {it["conversation_id"] for it in data["items"]} == {"c1", "c2"}
    assert data["items"][0]["nickname"] == "Alice"

    # 第一次 SQL 是 COUNT(*)，第二次是 SELECT 列
    assert db.execute.await_count == 2


def test_list_empty():
    db = _db_with([_result(scalar=0), _result(rows=[])])
    client = TestClient(_build_app(db=db))

    r = client.get("/api/v1/admin/conversations")
    assert r.status_code == 200
    data = r.json()
    assert data == {"items": [], "total": 0, "page": 1, "page_size": 20}


# ── filters / validation ───────────────────────────────────────────


def test_list_rejects_unknown_state():
    db = _db_with([])  # 不会被调到
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?state=BANANA")
    assert r.status_code == 400
    assert "state must be one of" in r.json()["detail"]
    db.execute.assert_not_awaited()


def test_list_rejects_unknown_channel():
    db = _db_with([])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?channel=fax")
    assert r.status_code == 400
    db.execute.assert_not_awaited()


def test_list_passes_search_as_ilike_param():
    db = _db_with([_result(scalar=0), _result(rows=[])])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?search=alice")
    assert r.status_code == 200

    # 检查 search 参数被 wrap 成 %alice%
    first_call_args = db.execute.await_args_list[0]
    params = first_call_args.args[1]
    assert params["search"] == "%alice%"
    assert params["state"] is None
    assert params["channel"] is None


def test_list_paging_offset_math():
    """page=3, page_size=20 → offset=40。"""
    db = _db_with([_result(scalar=0), _result(rows=[])])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?page=3&page_size=20")
    assert r.status_code == 200

    params = db.execute.await_args_list[1].args[1]
    assert params["limit"] == 20
    assert params["offset"] == 40


def test_list_rejects_page_size_too_large():
    db = _db_with([])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?page_size=999")
    assert r.status_code == 422


def test_list_rejects_page_zero():
    db = _db_with([])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations?page=0")
    assert r.status_code == 422


# ── detail ─────────────────────────────────────────────────────────


def test_detail_404_when_conversation_missing():
    db = _db_with([_result(rows=[])])  # head_row 为 None
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations/11111111-2222-3333-4444-555555555555")
    assert r.status_code == 404
    assert r.json()["detail"] == "conversation not found"


def test_detail_400_when_conversation_id_not_uuid():
    db = _db_with([])
    client = TestClient(_build_app(db=db))
    r = client.get("/api/v1/admin/conversations/not-a-uuid")
    assert r.status_code == 400
    db.execute.assert_not_awaited()


def test_detail_happy_path_returns_messages():
    head = _row({
        "conversation_id": "c1",
        "state": "AI_ACTIVE",
        "handoff_count": 0,
        "channel": "telegram",
        "last_message_at": None,
        "created_at": None,
        "assigned_operator_id": None,
        "ai_model_used": "gpt-x",
        "user_id": "u1",
        "nickname": "Alice",
        "external_id": "tg_111",
        "user_channel": "telegram",
        "risk_level": "normal",
        "user_status": "active",
        "language": "zh",
        "timezone": "UTC",
        "loneliness_score": 42.5,
        "vip_level": 0,
        "relationship_stage": "S0",
        "chat_style": "warm",
        "interests": ["音乐"],
        "forbidden_topics": [],
        "character_id": "ch1",
        "character_name": "Aria",
    })
    msg1 = _row({
        "id": "m1",
        "sender_type": "user",
        "content": "你好",
        "content_type": "text",
        "is_operator_message": False,
        "model_name": None,
        "safety_result": None,
        "created_at": None,
    })
    msg2 = _row({**msg1._mapping, "id": "m2", "sender_type": "assistant", "content": "嗨～", "model_name": "openrouter/x"})

    db = _db_with([_result(rows=[head]), _result(rows=[msg1, msg2])])
    client = TestClient(_build_app(db=db))

    r = client.get("/api/v1/admin/conversations/11111111-2222-3333-4444-555555555555")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["conversation"]["conversation_id"] == "c1"
    assert data["conversation"]["nickname"] == "Alice"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["id"] == "m1"
    assert data["messages"][1]["sender_type"] == "assistant"


def test_serialize_row_converts_decimal_to_float():
    """PG numeric -> Decimal; serializer must convert to float for JSON."""
    from decimal import Decimal

    from api.admin import _serialize_row

    row = MagicMock()
    row._mapping = {
        "loneliness_score": Decimal("42.5"),
        "total": Decimal("7"),
        "n": None,
        "u": uuid.UUID("00000000-0000-0000-0000-000000000001"),
    }
    out = _serialize_row(row)
    assert out["loneliness_score"] == 42.5
    assert out["total"] == 7
    assert out["n"] is None
    assert out["u"] == "00000000-0000-0000-0000-000000000001"
