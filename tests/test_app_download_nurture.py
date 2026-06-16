from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import app_download_nurture as nurture


class _RowsResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.executed.append((sql, params))
        if "user_message_count" in sql:
            return _RowsResult(
                [
                    {
                        "user_message_count": 2,
                        "last_user_at": datetime(2026, 5, 26, tzinfo=timezone.utc),
                        "last_assistant_at": datetime(2026, 5, 26, tzinfo=timezone.utc),
                        "has_click": False,
                        "has_download": False,
                    }
                ]
            )
        if "FROM user_profiles" in sql:
            return _RowsResult([{"user_level": "C", "preferences": {"country_code": "US"}}])
        if "SELECT sender_type, content, created_at" in sql:
            return _RowsResult(
                [
                    {"sender_type": "user", "content": "hello", "created_at": None},
                    {"sender_type": "user", "content": "still there?", "created_at": None},
                ]
            )
        if "UPDATE message_schedules" in sql and "superseded" in sql:
            return _RowsResult([])
        if "UPDATE message_schedules" in sql:
            return _RowsResult([])
        if "INSERT INTO message_schedules" in sql:
            return _RowsResult([("msg-1",)])
        return _RowsResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_schedule_skips_when_nurture_cycle_completed(monkeypatch):
    db = _FakeSession()

    async def _completed(**_kwargs):
        return True

    monkeypatch.setattr(nurture, "user_nurture_cycle_completed", _completed)

    queued = await nurture.schedule_nurture_after_reply(
        db,
        user_id="11111111-1111-1111-1111-111111111111",
        external_user_id="tg_123",
        conversation_id="22222222-2222-2222-2222-222222222222",
        chat_id=123,
        assistant_message_id="33333333-3333-3333-3333-333333333333",
        trace_id="trace",
    )

    assert queued == 0
    assert not any("INSERT INTO message_schedules" in sql for sql, _ in db.executed)


@pytest.mark.asyncio
async def test_user_nurture_cycle_completed_from_preferences():
    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "FROM user_profiles" in sql:
                return _RowsResult(
                    [{"preferences": {nurture.NURTURE_CYCLE_COMPLETED_PREF: "2026-05-26T00:00:00+00:00"}}]
                )
            raise AssertionError(f"unexpected query: {sql}")

    assert await nurture.user_nurture_cycle_completed(
        _Db(),
        user_id="11111111-1111-1111-1111-111111111111",
    )


@pytest.mark.asyncio
async def test_user_nurture_cycle_completed_when_all_rounds_sent():
    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "FROM user_profiles" in sql:
                return _RowsResult([{"preferences": {}}])
            if "COUNT(DISTINCT metadata->>'trigger')" in sql:
                return _RowsResult([(3,)])
            raise AssertionError(f"unexpected query: {sql}")

    assert await nurture.user_nurture_cycle_completed(
        _Db(),
        user_id="11111111-1111-1111-1111-111111111111",
    )


@pytest.mark.asyncio
async def test_should_skip_stale_when_nurture_cycle_completed(monkeypatch):
    class _Db:
        async def execute(self, statement, params=None):
            return _RowsResult([])

    async def _completed(**_kwargs):
        return True

    monkeypatch.setattr(nurture, "user_nurture_cycle_completed", _completed)

    reason = await nurture.should_skip_stale_nurture_message(
        _Db(),
        message={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "metadata": {
                "delivery_mode": nurture.APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "conversation_id": "22222222-2222-2222-2222-222222222222",
            },
        },
    )

    assert reason == "nurture_cycle_completed"


@pytest.mark.asyncio
async def test_schedules_three_video_round_followups(monkeypatch):
    db = _FakeSession()

    async def _search(**_kwargs):
        return type("Result", (), {"hits": []})()

    async def _not_completed(**_kwargs):
        return False

    monkeypatch.setattr(nurture, "search_script_templates", _search)
    monkeypatch.setattr(nurture, "user_nurture_cycle_completed", _not_completed)

    queued = await nurture.schedule_nurture_after_reply(
        db,
        user_id="11111111-1111-1111-1111-111111111111",
        external_user_id="tg_123",
        conversation_id="22222222-2222-2222-2222-222222222222",
        chat_id=123,
        assistant_message_id="33333333-3333-3333-3333-333333333333",
        trace_id="trace",
        account_id="44444444-4444-4444-4444-444444444444",
        telegram_access_hash=987654321,
        source="reply",
    )

    inserts = [params for sql, params in db.executed if "INSERT INTO message_schedules" in sql]
    assert queued == 3
    assert len(inserts) == 3
    triggers = [p["metadata"] for p in inserts]
    assert any(nurture.TRIGGER_NURTURE_ROUND_1 in meta for meta in triggers)
    assert any(nurture.TRIGGER_NURTURE_ROUND_2 in meta for meta in triggers)
    assert any(nurture.TRIGGER_NURTURE_ROUND_3 in meta for meta in triggers)
    assert all("video" in p["content"].casefold() or "视频" in p["content"] for p in inserts)
    assert all('"nurture_kind": "video_chat"' in p["metadata"] for p in inserts)
    assert all('"telegram_access_hash": "987654321"' in p["metadata"] for p in inserts)


def test_video_round_copy_zh():
    text = nurture._video_chat_round_copy(1, "zh")
    assert "视频" in text


def test_nurture_reply_language_uses_last_three_user_messages_only():
    history = [
        {"sender_type": "assistant", "content": "还在吗？要不要打个视频聊聊？"},
        {"sender_type": "user", "content": "HI"},
        {"sender_type": "user", "content": "thanks"},
        {"sender_type": "user", "content": "sounds good"},
    ]
    assert nurture._nurture_reply_language(history) == "en"


def test_nurture_reply_language_ignores_profile_language():
    history = [
        {"sender_type": "user", "content": "send me the app link"},
        {"sender_type": "user", "content": "where can I download"},
        {"sender_type": "user", "content": "hello"},
    ]
    assert nurture._nurture_reply_language(history) == "en"


def test_nurture_reply_language_prefers_chinese_when_recent_user_messages_are_chinese():
    history = [
        {"sender_type": "user", "content": "还在吗"},
        {"sender_type": "user", "content": "发我链接"},
        {"sender_type": "user", "content": "你好"},
    ]
    assert nurture._nurture_reply_language(history) == "zh"


def test_nurture_reply_language_detects_spanish():
    history = [
        {"sender_type": "user", "content": "hola mi vida"},
        {"sender_type": "user", "content": "quiero videollamada"},
        {"sender_type": "user", "content": "estoy aqui"},
    ]
    assert nurture._nurture_reply_language(history) == "es"


def test_nurture_reply_language_detects_portuguese():
    history = [
        {"sender_type": "user", "content": "oi cadê você"},
        {"sender_type": "user", "content": "quero chamada de vídeo"},
        {"sender_type": "user", "content": "estou aqui"},
    ]
    assert nurture._nurture_reply_language(history) == "pt"


def test_nurture_reply_language_detects_portuguese_sexo_agora():
    history = [
        {"sender_type": "user", "content": "SEXO AGORA"},
    ]
    assert nurture._nurture_reply_language(history) == "pt"


def test_nurture_reply_language_uses_profile_language_when_user_text_is_ambiguous():
    history = [
        {"sender_type": "user", "content": "hello"},
        {"sender_type": "user", "content": "thanks"},
    ]
    profile = {"preferences": {"nurture_language": "pt"}}
    assert nurture._nurture_reply_language(history, profile=profile) == "pt"


def test_video_round_copy_es_pt():
    assert "videollamada" in nurture._video_chat_round_copy(1, "es").casefold()
    assert "chamada" in nurture._video_chat_round_copy(2, "pt").casefold()


@pytest.mark.asyncio
async def test_stale_guard_ignores_spam_replies():
    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "e.event_type = 'download'" in sql:
                return _RowsResult([])
            if "SELECT content" in sql and "sender_type = 'user'" in sql:
                return _RowsResult(
                    [
                        ("Join https://t.me/+spam1 https://t.me/+spam2",),
                        ("yes",),
                    ]
                )
            return _RowsResult([])

    reason = await nurture.should_skip_stale_nurture_message(
        _Db(),
        message={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "metadata": {
                "delivery_mode": nurture.APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "conversation_id": "22222222-2222-2222-2222-222222222222",
                "cancel_if_user_message_after": "2026-05-26T00:00:00+00:00",
            },
        },
    )

    assert reason == "user_replied_after_queue"


@pytest.mark.asyncio
async def test_stale_guard_skips_when_user_replied_after_queue():
    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "e.event_type = 'download'" in sql:
                return _RowsResult([])
            if "SELECT content" in sql and "sender_type = 'user'" in sql:
                assert isinstance(params["stale_after"], datetime)
                return _RowsResult([("yes",)])
            return _RowsResult([])

    reason = await nurture.should_skip_stale_nurture_message(
        _Db(),
        message={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "metadata": {
                "delivery_mode": nurture.APP_DOWNLOAD_NURTURE_DELIVERY_MODE,
                "conversation_id": "22222222-2222-2222-2222-222222222222",
                "cancel_if_user_message_after": "2026-05-26T00:00:00+00:00",
            },
        },
    )

    assert reason == "user_replied_after_queue"


@pytest.mark.asyncio
async def test_cancel_superseded_round_followups_scoped_to_sender_account():
    db = _FakeSession()

    await nurture._cancel_superseded_round_followups(
        db,
        conversation_id="22222222-2222-2222-2222-222222222222",
        assistant_message_id="new-msg",
        sender_account_id="44444444-4444-4444-4444-444444444444",
    )

    cancel_sql, cancel_params = next(
        (sql, params) for sql, params in db.executed if "superseded" in sql
    )
    assert "sender_account_id" in cancel_sql
    assert cancel_params["sender_account_id"] == "44444444-4444-4444-4444-444444444444"
