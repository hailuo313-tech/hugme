from __future__ import annotations

import json

import pytest

from services import archive_service as svc


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _MappingsResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        sql = str(statement)
        if "SELECT c.id, c.user_id" in sql:
            return _MappingsResult(self.rows)
        if "INSERT INTO conversation_script_hits" in sql:
            return _ScalarResult("archive-1")
        return _MappingsResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_p3_18_claim_archive_task_selects_sent_script_hit_messages():
    session = _FakeSession(
        rows=[
            {
                "id": "source-msg-1",
                "user_id": "user-1",
                "external_user_id": "tg_1",
                "metadata": {"script_hit_id": "script-1"},
            }
        ]
    )

    task = await svc._claim_archive_task(session)

    sql = session.executed[0][0]
    assert task["id"] == "source-msg-1"
    assert "WHERE status = 'sent'" in sql
    assert "metadata->>'script_hit_id' IS NOT NULL" in sql
    assert "metadata->>'archive_skip_reason' IS NULL" in sql
    assert "conversation_script_hits" in sql
    assert session.commits == 1


@pytest.mark.asyncio
async def test_p3_18_create_archive_record_writes_source_message_and_script_ids():
    session = _FakeSession()

    archive_id = await svc._create_archive_record(
        session=session,
        conversation_id="11111111-1111-1111-1111-111111111111",
        message_id="22222222-2222-2222-2222-222222222222",
        script_hit_id="script-1",
        user_level="S",
        platform="telegram_real_user",
        source_message_id="33333333-3333-3333-3333-333333333333",
        metadata={"delivery_mode": "auto"},
        trace_id="trace-p3-18",
    )

    sql, params = session.executed[0]
    assert archive_id == "archive-1"
    assert "INSERT INTO conversation_script_hits" in sql
    assert params["hook"] == "archive"
    assert params["script_hit_id"] == "script-1"
    assert json.loads(params["script_ids"]) == ["script-1"]
    assert params["source_message_id"] == "33333333-3333-3333-3333-333333333333"
    assert json.loads(params["metadata"]) == {"delivery_mode": "auto"}
    assert session.commits == 1


@pytest.mark.asyncio
async def test_p3_18_run_one_tick_skips_orphan_conversation(monkeypatch):
    task = {
        "id": "source-msg-orphan",
        "user_id": "user-1",
        "external_user_id": "tg_1",
        "metadata": {
            "script_hit_id": "script-1",
            "conversation_id": "11b0678a-cc55-47db-9b24-a45b0555a15a",
        },
    }

    class _Session:
        def __init__(self):
            self.commits = 0

        async def execute(self, statement, params=None):
            sql = str(statement)
            if "pg_try_advisory_lock" in sql:
                return _ScalarResult(True)
            if "SELECT c.id, c.user_id" in sql:
                return _MappingsResult([task])
            if "SELECT 1 FROM conversations" in sql:
                return _MappingsResult([])
            if "UPDATE message_schedules" in sql:
                return _MappingsResult([])
            return _MappingsResult()

        async def commit(self):
            self.commits += 1

    session = _Session()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(svc, "AsyncSessionLocal", lambda: _Ctx())

    stats = await svc.run_one_tick(trace_id="trace-orphan")

    assert stats["claimed"] == 1
    assert stats["skipped_orphan"] == 1
    assert stats["archived"] == 0
    assert stats.get("failed", 0) == 0
