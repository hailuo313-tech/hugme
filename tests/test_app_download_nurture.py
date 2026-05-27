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
                        "user_message_count": 1,
                        "last_user_at": datetime(2026, 5, 26, tzinfo=timezone.utc),
                        "last_assistant_at": datetime(2026, 5, 26, tzinfo=timezone.utc),
                        "has_click": False,
                        "has_download": False,
                    }
                ]
            )
        if "SELECT * FROM user_profiles" in sql:
            return _RowsResult([{"user_level": "C", "preferences": {"country_code": "US", "age": 35}}])
        if "SELECT sender_type, content, created_at" in sql:
            return _RowsResult(
                [
                    {"sender_type": "user", "content": "I like women over 30", "created_at": None},
                    {"sender_type": "assistant", "content": "Nice", "created_at": None},
                ]
            )
        if "INSERT INTO message_schedules" in sql:
            return _RowsResult([("msg-1",)])
        return _RowsResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_first_message_idle_followup_is_queued_with_context(monkeypatch):
    db = _FakeSession()

    async def _url(_db):
        return "https://app.example/download"

    async def _search(**_kwargs):
        return type(
            "Result",
            (),
            {
                "hits": [
                    type(
                        "Hit",
                        (),
                        {
                            "id": "script-1",
                            "content": "Open this and we continue: {{app_download_url}}",
                        },
                    )()
                ]
            },
        )()

    monkeypatch.setattr(nurture, "resolve_app_download_url", _url)
    monkeypatch.setattr(nurture, "search_script_templates", _search)

    queued = await nurture.schedule_download_followups_after_reply(
        db,
        user_id="11111111-1111-1111-1111-111111111111",
        external_user_id="tg_123",
        conversation_id="22222222-2222-2222-2222-222222222222",
        chat_id=123,
        assistant_message_id="33333333-3333-3333-3333-333333333333",
        trace_id="trace",
        account_id="44444444-4444-4444-4444-444444444444",
    )

    assert queued >= 1
    insert_params = [params for sql, params in db.executed if "INSERT INTO message_schedules" in sql][0]
    assert insert_params["message_type"] == nurture.APP_DOWNLOAD_MESSAGE_TYPE
    assert "I like women over 30" in insert_params["content"]
    assert "https://app.example/download" in insert_params["content"]
    assert '"delivery_mode": "app_download_nurture"' in insert_params["metadata"]
    assert '"trigger": "first_message_idle_3m"' in insert_params["metadata"]
    assert insert_params["account_id"] == "44444444-4444-4444-4444-444444444444"


@pytest.mark.asyncio
async def test_stale_guard_skips_when_user_replied_after_queue():
    class _Db:
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "e.event_type = 'download'" in sql:
                return _RowsResult([])
            if "sender_type = 'user'" in sql:
                return _RowsResult([(1,)])
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
async def test_clicked_no_download_scan_is_recent_and_dedupes_failed(monkeypatch):
    class _ClickedSession(_FakeSession):
        async def execute(self, statement, params=None):
            sql = str(statement)
            self.executed.append((sql, params or {}))
            if "WITH clicked AS" in sql:
                return _RowsResult(
                    [
                        {
                            "tracking_id": "track-1",
                            "user_id": "11111111-1111-1111-1111-111111111111",
                            "conversation_id": "22222222-2222-2222-2222-222222222222",
                            "external_user_id": "tg_123",
                            "chat_id": 123,
                            "clicked_at": datetime(2026, 5, 26, tzinfo=timezone.utc),
                        }
                    ]
                )
            if "INSERT INTO message_schedules" in sql:
                return _RowsResult([("msg-1",)])
            return _RowsResult()

    db = _ClickedSession()

    async def _build_content(_db, **_kwargs):
        return "continue here: https://app.example/download", {}

    monkeypatch.setattr(nurture, "_build_contextual_content", _build_content)

    await nurture.queue_clicked_not_downloaded_followups(db, trace_id="trace", batch_size=5)

    scan_sql = db.executed[0][0]
    insert_sql = [sql for sql, _ in db.executed if "INSERT INTO message_schedules" in sql][0]
    assert "INTERVAL '24 hours'" in scan_sql
    assert "'app_link_clicked_followup'" not in scan_sql
    assert "ROW_NUMBER() OVER" in scan_sql
    assert "ms.metadata->>'conversation_id' = c.conversation_id" in scan_sql
    assert "ms.status IN ('pending', 'sending', 'sent', 'failed')" in scan_sql
    assert "status IN ('pending', 'sending', 'sent', 'failed')" in insert_sql
