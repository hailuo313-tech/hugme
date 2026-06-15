"""Tests for telegram_peer_cache asyncpg-safe SQL."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from services.telegram_peer_cache import resolve_cached_telegram_peer, upsert_telegram_peer_cache


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params or {}))
        if "FROM telegram_peer_cache" in sql:
            return _FakeResult(
                {
                    "account_id": params.get("account_id") or "acct-1",
                    "chat_id": params.get("chat_id") or 123,
                    "access_hash": 99,
                    "user_id": params.get("user_id"),
                    "conversation_id": params.get("conversation_id"),
                    "last_seen_at": None,
                }
            )
        return _FakeResult(None)

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_upsert_sql_does_not_use_nullable_case_params():
    db = _FakeSession()
    await upsert_telegram_peer_cache(
        db,
        user_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        account_id="33333333-3333-3333-3333-333333333333",
        chat_id=4242,
        access_hash=77,
        source="test",
    )
    sql, params = db.executed[0]
    assert "CASE WHEN" not in sql
    assert "CAST(:user_id AS uuid)" in sql
    assert params["chat_id"] == 4242


@pytest.mark.asyncio
async def test_resolve_sql_uses_coalesce_filters_without_duplicate_params():
    db = _FakeSession()
    row = await resolve_cached_telegram_peer(
        db,
        conversation_id="22222222-2222-2222-2222-222222222222",
        user_id="11111111-1111-1111-1111-111111111111",
        account_id="33333333-3333-3333-3333-333333333333",
        chat_id=4242,
    )
    sql, params = db.executed[0]
    assert "COALESCE(CAST(:conversation_id AS uuid), conversation_id)" in sql
    assert sql.count(":account_id") == 1
    assert row is not None
    assert row["chat_id"] == 4242
