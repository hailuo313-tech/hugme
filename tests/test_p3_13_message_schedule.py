from __future__ import annotations

import pytest

from services import message_schedule_service as svc


class _MappingsResult:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        sql = str(statement)
        if "RETURNING ms.id" in sql:
            return _MappingsResult(self.rows)
        return _MappingsResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_p3_13_claim_one_message_uses_send_at_priority_and_commits():
    session = _FakeSession(
        rows=[
            {
                "id": "msg-1",
                "user_id": "user-1",
                "external_user_id": "tg_1",
                "message_type": "text",
                "content": "hello",
                "platform": "telegram_real_user",
                "account_id": "acc-1",
                "chat_id": 123,
                "metadata": {},
                "trace_id": "trace-1",
                "retry_count": 0,
            }
        ]
    )

    message = await svc._claim_one_message(session)

    sql = session.executed[0][0]
    assert message["id"] == "msg-1"
    assert "WHERE status = 'pending'" in sql
    assert "send_at <= NOW()" in sql
    assert "ORDER BY priority DESC, send_at ASC" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert session.commits == 1


@pytest.mark.asyncio
async def test_p3_13_finalize_message_marks_sent_or_failed():
    session = _FakeSession()

    await svc._finalize_message(session, message_id="msg-1", status="sent")
    await svc._finalize_message(
        session,
        message_id="msg-2",
        status="failed",
        failure_reason="telegram_send_failed",
    )

    sent_sql, sent_params = session.executed[0]
    failed_sql, failed_params = session.executed[1]
    assert "SET status = 'sent'" in sent_sql
    assert sent_params == {"id": "msg-1"}
    assert "SET status = 'failed'" in failed_sql
    assert "retry_count = retry_count + 1" in failed_sql
    assert failed_params == {"id": "msg-2", "reason": "telegram_send_failed"}
    assert session.commits == 2


def test_p3_13_start_scheduler_respects_enabled_flag(monkeypatch):
    monkeypatch.setattr(svc, "_scheduler", None)
    monkeypatch.setattr(svc.settings, "MESSAGE_SCHEDULE_ENABLED", False)

    svc.start_scheduler()

    assert svc._scheduler is None


def test_p3_13_start_scheduler_initializes_when_enabled(monkeypatch):
    class _FakeScheduler:
        def __init__(self):
            self.running = False
            self.jobs = []

        def add_job(self, *args, **kwargs):
            self.jobs.append((args, kwargs))

        def start(self):
            self.running = True

    monkeypatch.setattr(svc, "_scheduler", None)
    monkeypatch.setattr(svc, "AsyncIOScheduler", _FakeScheduler)
    monkeypatch.setattr(svc, "IntervalTrigger", lambda **kwargs: ("interval", kwargs))
    monkeypatch.setattr(svc.settings, "MESSAGE_SCHEDULE_ENABLED", True)

    svc.start_scheduler()

    assert svc._scheduler is not None
    assert svc._scheduler.running is True
    assert svc._scheduler.jobs
