from __future__ import annotations

import pytest

from services.inbound.queue_consumer import (
    DEFAULT_CONSUMER_GROUP,
    INBOUND_QUEUE_STREAM,
    ensure_consumer_group,
    process_inbound_queue_once,
    read_inbound_queue,
)


class FakeRedis:
    def __init__(self, *, busygroup: bool = False):
        self.busygroup = busygroup
        self.created_groups = []
        self.acked = []
        self.read_calls = []

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        self.created_groups.append((stream, group, id, mkstream))
        if self.busygroup:
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        self.read_calls.append((group, consumer, streams, count, block))
        return [
            (
                INBOUND_QUEUE_STREAM.encode(),
                [
                    (
                        b"1700000000000-0",
                        {
                            b"platform": b"telegram_real_user",
                            b"external_user_id": b"tg_42",
                            b"message_type": b"text",
                            b"content": b"hello",
                            b"trace_id": b"trace-123456",
                            b"account_id": b"acc_1",
                            b"sender_phone": b"+15551234567",
                            b"metadata": b'{"telegram_message_id":"99"}',
                        },
                    )
                ],
            )
        ]

    async def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))


class FakeDbResult:
    def mappings(self):
        return self

    def all(self):
        return []


class FakeDb:
    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return FakeDbResult()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_p1_06_consumer_group_creation_ignores_busygroup():
    redis = FakeRedis(busygroup=True)

    await ensure_consumer_group(redis)

    assert redis.created_groups == [
        (INBOUND_QUEUE_STREAM, DEFAULT_CONSUMER_GROUP, "0", True)
    ]


@pytest.mark.asyncio
async def test_p1_06_read_inbound_queue_normalizes_fields():
    redis = FakeRedis()

    entries = await read_inbound_queue(redis, consumer="worker-1", count=1, block_ms=10)

    assert redis.read_calls == [
        (
            DEFAULT_CONSUMER_GROUP,
            "worker-1",
            {INBOUND_QUEUE_STREAM: ">"},
            1,
            10,
        )
    ]
    assert entries[0][0] == "1700000000000-0"
    assert entries[0][1]["external_user_id"] == "tg_42"
    assert entries[0][1]["metadata"] == {"telegram_message_id": "99"}


@pytest.mark.asyncio
async def test_p1_06_processes_entry_writes_audit_and_acks():
    redis = FakeRedis()
    db = FakeDb()
    handled = []

    async def handler(fields):
        handled.append(fields)

    processed = await process_inbound_queue_once(
        redis,
        db,
        handler=handler,
        consumer="worker-1",
        count=1,
        block_ms=10,
    )

    assert processed == 1
    assert db.commits == 1
    assert handled[0]["platform"] == "telegram_real_user"
    assert redis.acked == [
        (INBOUND_QUEUE_STREAM, DEFAULT_CONSUMER_GROUP, "1700000000000-0")
    ]
    sql, params = db.executed[0]
    assert "INSERT INTO audit_logs" in sql
    assert params["event_type"] == "inbound_queue.consumed"
    assert params["user_id"] == "tg_42"
    assert "1700000000000-0" in params["payload"]
