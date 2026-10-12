from __future__ import annotations

import pytest

from services.user_report import (
    fetch_user_collection_users,
    fetch_user_report_overview,
    fetch_user_report_trend,
    validate_range,
)


class _Mappings:
    def __init__(self, value):
        self.value = value

    def one(self):
        return self.value

    def all(self):
        return self.value


class _Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return _Mappings(self.value)

    def scalar(self):
        return self.value


class _Db:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.values.pop(0))


def test_validate_range_accepts_supported_values():
    assert validate_range("today") == "today"
    assert validate_range(" HISTORY ") == "history"


def test_validate_range_rejects_unknown_value():
    with pytest.raises(ValueError):
        validate_range("quarter")


@pytest.mark.asyncio
async def test_overview_returns_mapping_and_binds_range():
    db = _Db([{"new_users": 3, "active_users": 2}])
    result = await fetch_user_report_overview(db, "week")
    assert result == {"new_users": 3, "active_users": 2}
    assert db.calls[0][1] == {"range_key": "week"}
    assert "Asia/Shanghai" in db.calls[0][0]


@pytest.mark.asyncio
async def test_trend_returns_rows():
    db = _Db([[{"label": "08-17", "new_users": 1, "active_users": 1, "engaged_users": 0}]])
    result = await fetch_user_report_trend(db, "today")
    assert result[0]["label"] == "08-17"


@pytest.mark.asyncio
async def test_collection_users_skips_rows_already_cached():
    db = _Db([0, []])
    result = await fetch_user_collection_users(
        db, "today", after_created_at="2026-08-30T03:00:00+00:00"
    )
    assert result["total"] == 0
    assert result["items"] == []
    sql, params = db.calls[0]
    assert "u.created_at > CAST(:after_created_at AS timestamptz)" in sql
    assert params["after_created_at"] == "2026-08-30T03:00:00+00:00"


@pytest.mark.asyncio
async def test_collection_users_full_list_omits_after_filter():
    db = _Db([0, []])
    await fetch_user_collection_users(db, "today")
    sql, params = db.calls[0]
    assert "u.created_at > CAST(:after_created_at AS timestamptz)" not in sql
    assert params["after_created_at"] is None


@pytest.mark.asyncio
async def test_collection_users_search_covers_all_users():
    db = _Db([0, []])
    await fetch_user_collection_users(db, "today", search="tg_123")
    sql = db.calls[0][0]
    assert "WITH matched AS" in sql
    assert "u.created_at >= p.start_at" not in sql
    assert "ILIKE :search" in sql
