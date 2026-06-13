"""Conversation AI replies no longer run reply_consistency checks."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api import conversations as cv


class _Row:
    def __init__(self, values: tuple[Any, ...] = (), mapping: dict[str, Any] | None = None):
        self._values = values
        self._mapping = mapping or {}

    def __getitem__(self, idx: int) -> Any:
        return self._values[idx]


class _Result:
    def __init__(self, row: _Row | None = None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commit = AsyncMock()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "SELECT id, user_id FROM conversations" in sql:
            return _Result(_Row(("conv-1", "user-1")))
        if "SELECT id, content FROM messages" in sql:
            return _Result(_Row(("msg-1", "hello")))
        return _Result(None)


class _FakeRedis:
    def pipeline(self):
        return self

    def rpush(self, *_args):
        return self

    def ltrim(self, *_args):
        return self

    def expire(self, *_args):
        return self

    async def execute(self):
        return []


@pytest.mark.asyncio
async def test_conversation_reply_persists_orchestrator_text_unchanged(monkeypatch):
    db = _FakeDB()
    llm_reply = "As ChatGPT, I am a large language model."
    monkeypatch.setattr(cv, "get_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(cv, "generate_reply", AsyncMock(return_value=llm_reply))
    monkeypatch.setattr(cv, "wrap_text_links_with_tracking", AsyncMock(return_value=llm_reply))
    monkeypatch.setattr(cv, "get_last_app_download_decision", lambda: None)

    request = SimpleNamespace(state=SimpleNamespace(trace_id="trace-consistency"))
    out = await cv.ai_reply("conv-1", request, db=db)

    insert_calls = [c for c in db.calls if "INSERT INTO messages" in c[0]]
    assert insert_calls
    _sql, params = insert_calls[0]
    assert params["ct"] == llm_reply
    assert out["reply_content"] == llm_reply
    db.commit.assert_awaited_once()
