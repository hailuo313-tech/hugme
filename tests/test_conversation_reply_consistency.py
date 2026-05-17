"""P2 ConsistencyScore integration for conversation AI replies."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api import conversations as cv
from services.reply_consistency import DEFAULT_FALLBACK_REPLY


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
        if "LEFT JOIN characters" in sql:
            return _Result(
                _Row(
                    mapping={
                        "id": "char-1",
                        "name": "Aria",
                        "reply_length": "short",
                        "emoji_frequency": "none",
                        "boundary_score": 80,
                    }
                )
            )
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
async def test_conversation_reply_writes_consistency_score_and_fallback(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(cv, "get_redis", AsyncMock(return_value=_FakeRedis()))
    monkeypatch.setattr(
        cv,
        "generate_reply",
        AsyncMock(return_value="As ChatGPT, I am a large language model."),
    )

    request = SimpleNamespace(state=SimpleNamespace(trace_id="trace-consistency"))
    out = await cv.ai_reply("conv-1", request, db=db)

    insert_calls = [c for c in db.calls if "INSERT INTO messages" in c[0]]
    assert insert_calls
    _sql, params = insert_calls[0]
    assert "consistency_score" in _sql
    assert params["ct"] == DEFAULT_FALLBACK_REPLY
    assert params["cs"] < 0.65
    assert out["reply_content"] == DEFAULT_FALLBACK_REPLY
    db.commit.assert_awaited_once()
