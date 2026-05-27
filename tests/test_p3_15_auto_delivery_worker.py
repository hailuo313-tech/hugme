from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import auto_delivery_worker as worker


class _MappingsResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params or {}))
        if "pg_try_advisory_lock" in sql:
            return _ScalarResult(True)
        if "pg_advisory_unlock" in sql:
            return _ScalarResult(True)
        if "RETURNING ms.id" in sql:
            return _MappingsResult(self.rows)
        return _MappingsResult()

    async def commit(self):
        self.commits += 1


class _FakePool:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(account_id="acc-1")


@pytest.mark.asyncio
async def test_p3_15_claim_bcd_message_allows_bcd_and_timeout_fallbacks():
    session = _FakeSession(
        rows=[
            {
                "id": "msg-1",
                "user_id": "user-1",
                "external_user_id": "tg_1",
                "message_type": "text",
                "content": "hello",
                "platform": "telegram_real_user",
                "account_id": None,
                "chat_id": 123,
                "metadata": {},
                "trace_id": "trace-1",
                "retry_count": 0,
            }
        ]
    )

    message = await worker._claim_bcd_message(session)

    sql, params = session.executed[0]
    assert message["id"] == "msg-1"
    assert "COALESCE(p.user_level, 'C') IN ('B', 'C', 'D')" in sql
    assert "LEFT JOIN user_profiles p ON p.user_id = u.id" in sql
    assert "ms.metadata->>'delivery_mode' = :delivery_mode" in sql
    assert "ms.metadata->>'delivery_mode' = :app_download_delivery_mode" in sql
    assert params["delivery_mode"] == worker.TIMEOUT_FALLBACK_DELIVERY_MODE
    assert params["timeout_message_type"] == worker.TIMEOUT_FALLBACK_MESSAGE_TYPE
    assert params["app_download_delivery_mode"] == worker.APP_DOWNLOAD_NURTURE_DELIVERY_MODE
    assert params["app_download_message_type"] == worker.APP_DOWNLOAD_MESSAGE_TYPE
    assert session.commits == 1


def test_p3_15_timeout_fallback_message_detection():
    assert worker._is_timeout_fallback_message(
        {"message_type": worker.TIMEOUT_FALLBACK_MESSAGE_TYPE, "metadata": {}}
    )
    assert worker._is_timeout_fallback_message(
        {"message_type": "text", "metadata": {"delivery_mode": worker.TIMEOUT_FALLBACK_DELIVERY_MODE}}
    )
    assert not worker._is_timeout_fallback_message({"message_type": "text", "metadata": {}})


def test_p3_15_start_scheduler_initializes_scheduler(monkeypatch):
    class _FakeScheduler:
        def __init__(self):
            self.running = False
            self.jobs = []

        def add_job(self, *args, **kwargs):
            self.jobs.append((args, kwargs))

        def start(self):
            self.running = True

    created_tasks = []

    monkeypatch.setattr(worker, "_scheduler", None)
    monkeypatch.setattr(worker, "AsyncIOScheduler", _FakeScheduler)
    monkeypatch.setattr(worker, "IntervalTrigger", lambda **kwargs: ("interval", kwargs))
    monkeypatch.setattr(worker.settings, "AUTO_DELIVERY_ENABLED", True)
    def _capture_task(coro):
        created_tasks.append(coro)
        coro.close()

    monkeypatch.setattr(worker.asyncio, "create_task", _capture_task)

    worker.start_scheduler()

    assert worker._scheduler is not None
    assert worker._scheduler.running is True
    assert worker._scheduler.jobs
    assert created_tasks


def test_p3_15_scheduler_status_handles_apscheduler(monkeypatch):
    class _FakeScheduler:
        running = True

        def get_job(self, job_id):
            return object() if job_id == worker.JOB_ID else None

    monkeypatch.setattr(worker, "_scheduler", _FakeScheduler())
    monkeypatch.setattr(worker, "_account_pool", object())

    status = worker.get_scheduler_status()

    assert status["running"] is True
    assert status["job_exists"] is True
    assert status["account_pool_initialized"] is True


@pytest.mark.asyncio
async def test_p3_15_run_one_tick_releases_advisory_lock(monkeypatch):
    session = _FakeSession(rows=[])

    class _SessionFactory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(worker, "_account_pool", _FakePool())
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _SessionFactory())
    monkeypatch.setattr(worker, "schedule_expired_timeout_fallbacks", lambda *_args, **_kwargs: _async_zero())
    monkeypatch.setattr(worker, "queue_clicked_not_downloaded_followups", lambda *_args, **_kwargs: _async_zero())

    stats = await worker.run_one_tick(trace_id="trace-lock")

    sql_texts = [sql for sql, _ in session.executed]
    assert stats["claimed"] == 0
    assert any("pg_try_advisory_lock" in sql for sql in sql_texts)
    assert any("pg_advisory_unlock" in sql for sql in sql_texts)


async def _async_zero():
    return 0


def test_p3_15_timeout_fallback_locks_handoff_tasks_only():
    import inspect

    source = inspect.getsource(worker.schedule_expired_timeout_fallbacks)
    assert "LEFT JOIN user_profiles" in source
    assert "FOR UPDATE OF ht SKIP LOCKED" in source


def test_p3_15_bcd_claim_locks_message_schedule_rows_only():
    import inspect

    source = inspect.getsource(worker._claim_bcd_message)
    assert "LEFT JOIN user_profiles" in source
    assert "FOR UPDATE OF ms SKIP LOCKED" in source


@pytest.mark.asyncio
async def test_p3_15_send_via_account_pool_uses_human_delay(monkeypatch):
    fake_pool = _FakePool()
    monkeypatch.setattr(worker, "_account_pool", fake_pool)
    monkeypatch.setattr(
        worker,
        "calculate_human_delay",
        lambda _content: SimpleNamespace(delay_seconds=0),
    )

    success = await worker._send_via_account_pool(
        user_id="user-1",
        chat_id=123,
        content="hello",
        trace_id="trace-p3-15",
    )

    assert success is True
    assert fake_pool.sent[0]["user_id"] == "user-1"
    assert fake_pool.sent[0]["text"] == "hello"
