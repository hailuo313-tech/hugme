from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.mtproto import auto_reply


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Db:
    def __init__(self, prefs: dict | None = None):
        self.prefs = prefs or {}
        self.execute = AsyncMock(side_effect=self._execute)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def _execute(self, query, params=None):
        sql = str(query)
        if "SELECT preferences" in sql:
            return _Result(SimpleNamespace(_mapping={"preferences": self.prefs}))
        return _Result()


@pytest.mark.asyncio
async def test_mtproto_profile_intake_asks_country_when_missing(monkeypatch):
    db = _Db({})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code=None, age=None)),
    )

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="hi",
        log=SimpleNamespace(info=lambda *a, **k: None, bind=lambda **k: SimpleNamespace(info=lambda *a, **kw: None)),
    )

    assert reply == auto_reply.PROFILE_COUNTRY_QUESTION
    assert db.prefs["profile_intake_pending"] == "country"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mtproto_profile_intake_retries_unrecognized_country(monkeypatch):
    db = _Db({"profile_intake_pending": "country"})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code=None, age=None)),
    )

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="somewhere",
        log=SimpleNamespace(info=lambda *a, **k: None, bind=lambda **k: SimpleNamespace(info=lambda *a, **kw: None)),
    )

    assert reply == auto_reply.PROFILE_COUNTRY_QUESTION


@pytest.mark.asyncio
async def test_mtproto_profile_intake_collects_country_then_asks_age(monkeypatch):
    db = _Db({"profile_intake_pending": "country"})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code=None, age=None)),
    )
    write_country = AsyncMock()
    monkeypatch.setattr(auto_reply, "write_country_code", write_country)
    level_service = SimpleNamespace(calculate_and_persist_user_level=AsyncMock(return_value={}))
    monkeypatch.setattr(auto_reply, "user_level_service", level_service)

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="United States",
        log=SimpleNamespace(info=lambda *a, **k: None, bind=lambda **k: SimpleNamespace(info=lambda *a, **kw: None)),
    )

    assert reply == auto_reply.PROFILE_AGE_QUESTION
    assert db.prefs["profile_intake_pending"] == "age"
    write_country.assert_awaited_once()
    level_service.calculate_and_persist_user_level.assert_awaited_once()
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_mtproto_profile_intake_keeps_country_when_level_recalc_fails(monkeypatch):
    db = _Db({"profile_intake_pending": "country"})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code=None, age=None)),
    )
    write_country = AsyncMock()
    monkeypatch.setattr(auto_reply, "write_country_code", write_country)
    level_service = SimpleNamespace(
        calculate_and_persist_user_level=AsyncMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(auto_reply, "user_level_service", level_service)
    log = SimpleNamespace(
        info=lambda *a, **k: None,
        bind=lambda **k: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
        ),
    )

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="US",
        log=log,
    )

    assert reply == auto_reply.PROFILE_AGE_QUESTION
    assert db.prefs["profile_intake_pending"] == "age"
    write_country.assert_awaited_once()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_mtproto_profile_intake_collects_age_then_acknowledges(monkeypatch):
    db = _Db({"profile_intake_pending": "age"})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code="US", age=None)),
    )
    write_age = AsyncMock()
    monkeypatch.setattr(auto_reply, "write_age", write_age)
    level_service = SimpleNamespace(calculate_and_persist_user_level=AsyncMock(return_value={}))
    monkeypatch.setattr(auto_reply, "user_level_service", level_service)

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="29",
        log=SimpleNamespace(info=lambda *a, **k: None, bind=lambda **k: SimpleNamespace(info=lambda *a, **kw: None)),
    )

    assert reply is None
    assert "profile_intake_pending" not in db.prefs
    write_age.assert_awaited_once()
    level_service.calculate_and_persist_user_level.assert_awaited_once()
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_mtproto_profile_intake_asks_age_without_blocking_when_missing(monkeypatch):
    db = _Db({"profile_intake_pending": "age"})
    monkeypatch.setattr(
        auto_reply,
        "read_profile_completeness",
        AsyncMock(return_value=SimpleNamespace(country_code="US", age=None)),
    )

    reply = await auto_reply._handle_required_profile_intake(
        db,
        user_id="00000000-0000-0000-0000-000000000001",
        external_id="tg_1",
        text_value="not telling",
        log=SimpleNamespace(info=lambda *a, **k: None, bind=lambda **k: SimpleNamespace(info=lambda *a, **kw: None)),
    )

    assert reply == auto_reply.PROFILE_AGE_QUESTION
