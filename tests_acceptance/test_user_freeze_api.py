"""P2: POST /users/{id}/freeze."""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.messages import router as messages_router
from api.users import router as users_router
from core.database import get_db

USER_ID = "00000000-0000-0000-0000-000000000501"


def _result(*, one: Any | None = None, rows: list[Any] | None = None) -> MagicMock:
    res = MagicMock()
    res.fetchone.return_value = one
    res.fetchall.return_value = rows or []
    return res


def _app(db: Any, *, with_auth: bool = True, include_messages: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1/users")
    if include_messages:
        app.include_router(messages_router, prefix="/api/v1/messages")

    async def _fake_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": "op", "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_freeze_user_requires_operator():
    db = MagicMock()
    client = TestClient(_app(db, with_auth=False))

    r = client.post(f"/api/v1/users/{USER_ID}/freeze")

    assert r.status_code == 401


def test_freeze_user_updates_user_conversations_and_notifications():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(one=(USER_ID, "frozen")),
            _result(rows=[("conv-1",), ("conv-2",)]),
            _result(rows=[("notif-1",)]),
        ]
    )
    db.commit = AsyncMock()
    client = TestClient(_app(db))

    r = client.post(
        f"/api/v1/users/{USER_ID}/freeze",
        json={"reason": "abuse"},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data == {
        "status": "frozen",
        "user_id": USER_ID,
        "conversations_frozen": 2,
        "notifications_cancelled": 1,
    }
    sqls = [str(call.args[0]) for call in db.execute.await_args_list]
    assert any("UPDATE users" in sql and "status = 'frozen'" in sql for sql in sqls)
    assert any("UPDATE conversations" in sql and "FROZEN" in sql for sql in sqls)
    assert any("UPDATE notification_tasks" in sql and "cancelled" in sql for sql in sqls)
    db.commit.assert_awaited_once()


def test_freeze_user_not_found():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=None))
    client = TestClient(_app(db))

    r = client.post(f"/api/v1/users/{USER_ID}/freeze")

    assert r.status_code == 404


def test_freeze_user_rejects_bad_uuid():
    db = MagicMock()
    client = TestClient(_app(db))

    r = client.post("/api/v1/users/not-a-uuid/freeze")

    assert r.status_code == 400
    assert "valid UUID" in r.json()["detail"]


def test_inbound_message_blocks_frozen_user(monkeypatch):
    class _Redis:
        async def get(self, *_args):
            return None

    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(one=(USER_ID, "frozen")))
    monkeypatch.setattr("api.messages.get_redis", AsyncMock(return_value=_Redis()))
    client = TestClient(_app(db, include_messages=True))

    r = client.post(
        "/api/v1/messages/inbound",
        json={
            "channel": "telegram",
            "external_user_id": "tg_1",
            "message_type": "text",
            "content": "hello",
        },
    )

    assert r.status_code == 423, r.text
    assert r.json()["status"] == "blocked_by_user_status"
    assert r.json()["block_reason"] == "user_status:frozen"
