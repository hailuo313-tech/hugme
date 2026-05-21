from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.audit_log_service import (
    RECENT_AUDIT_LIMIT,
    get_recent_audit_logs,
    record_audit_log,
    serialize_audit_row,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return FakeResult(self.rows)


@pytest.mark.asyncio
async def test_p1_16_record_audit_log_inserts_structured_payload():
    db = FakeDb()

    await record_audit_log(
        db,
        event_type="inbound_queue.consumed",
        source="inbound_queue_consumer",
        trace_id="trace-123456",
        user_id="tg_42",
        platform="telegram_real_user",
        account_id="acc_1",
        sender_phone="+15551234567",
        payload={"redis_message_id": "1700000000000-0"},
    )

    sql, params = db.executed[0]
    assert "INSERT INTO audit_logs" in sql
    assert params["event_type"] == "inbound_queue.consumed"
    assert params["source"] == "inbound_queue_consumer"
    assert params["payload"] == '{"redis_message_id": "1700000000000-0"}'


@pytest.mark.asyncio
async def test_p1_16_recent_query_is_capped_at_100_and_redacts_phone():
    db = FakeDb(
        rows=[
            {
                "id": "audit-1",
                "trace_id": "trace-123456",
                "event_type": "inbound_queue.consumed",
                "source": "inbound_queue_consumer",
                "actor_type": "system",
                "actor_id": None,
                "user_id": "tg_42",
                "conversation_id": None,
                "message_id": None,
                "platform": "telegram_real_user",
                "account_id": "acc_1",
                "sender_phone": "+15551234567",
                "script_hit_id": None,
                "payload": {"redis_message_id": "1700000000000-0"},
                "created_at": datetime(2026, 5, 21, tzinfo=timezone.utc),
            }
        ]
    )

    rows = await get_recent_audit_logs(db, limit=500)

    sql, params = db.executed[0]
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT :limit" in sql
    assert params["limit"] == RECENT_AUDIT_LIMIT
    assert rows[0]["sender_phone"].endswith("4567")
    assert rows[0]["sender_phone"] != "+15551234567"
    assert rows[0]["created_at"] == "2026-05-21T00:00:00+00:00"


def test_p1_16_serialize_audit_row_parses_json_payload():
    row = {
        "id": "audit-1",
        "sender_phone": "1234",
        "payload": '{"ok": true}',
    }

    serialized = serialize_audit_row(row)

    assert serialized["payload"] == {"ok": True}
    assert serialized["sender_phone"] == "****"
