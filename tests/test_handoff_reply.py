"""V001-P0-1：handoff operator reply 写库 + Telegram 发送。"""
from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin import require_operator
from api.handoff import router
from core.database import get_db

TASK_ID = "00000000-0000-0000-0000-000000000010"
CONV_ID = "00000000-0000-0000-0000-000000000020"
USER_ID = "00000000-0000-0000-0000-000000000030"


def _row(d: dict[str, Any]) -> MagicMock:
    r = MagicMock()
    r._mapping = d
    return r


def _mini_app(db: Any, *, with_auth: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/handoff")

    async def _fake_get_db() -> AsyncGenerator[Any, None]:
        yield db

    app.dependency_overrides[get_db] = _fake_get_db

    if with_auth:

        async def _fake_operator() -> dict:
            return {"sub": "op-1", "type": "operator", "role": "admin"}

        app.dependency_overrides[require_operator] = _fake_operator

    return app


def test_handoff_reply_401_without_token():
    db = MagicMock()
    app = _mini_app(db, with_auth=False)
    with TestClient(app) as client:
        r = client.post(
            f"/api/v1/handoff/{TASK_ID}/reply",
            json={"content": "hello"},
        )
    assert r.status_code == 401


@patch("api.handoff.send_telegram_text", new_callable=AsyncMock)
@patch("api.handoff.get_redis", new_callable=AsyncMock)
def test_handoff_reply_200(mock_redis, mock_send):
    task_row = _row(
        {
            "task_id": TASK_ID,
            "conversation_id": CONV_ID,
            "task_status": "HUMAN_LOCKED",
            "user_id": USER_ID,
            "channel": "telegram",
            "external_id": "tg_123456789",
        }
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=lambda: task_row))
    db.commit = AsyncMock()

    mock_send.return_value = 999
    redis = MagicMock()
    redis.pipeline.return_value = MagicMock(
        rpush=MagicMock(),
        ltrim=MagicMock(),
        expire=MagicMock(),
        execute=AsyncMock(),
    )
    mock_redis.return_value = redis

    app = _mini_app(db)
    with TestClient(app) as client:
        r = client.post(
            f"/api/v1/handoff/{TASK_ID}/reply",
            json={"content": "运营来了"},
            headers={"Authorization": "Bearer x"},
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "sent"
    assert data["telegram_message_id"] == 999
    assert uuid.UUID(data["message_id"])
    mock_send.assert_awaited_once()
    assert mock_send.await_args.kwargs["chat_id"] == 123456789
