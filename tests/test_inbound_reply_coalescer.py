from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.inbound_reply_coalescer import (
    finalize_coalesced_inbound_turn,
    merge_coalesced_user_text,
    register_inbound_turn,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
            self.lists.pop(key, None)

    async def lrange(self, key: str, start: int, end: int):
        items = self.lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        return items[start : end + 1]

    def pipeline(self):
        redis = self
        pending_incr_key: str | None = None

        class _Pipe:
            def rpush(self, key: str, value: str):
                redis.lists.setdefault(key, []).append(value)

            def expire(self, key: str, ttl: int):
                return None

            def incr(self, key: str):
                nonlocal pending_incr_key
                pending_incr_key = key
                redis.values[key] = int(redis.values.get(key, 0)) + 1

            async def execute(self):
                return [None, None, redis.values[pending_incr_key], None]

        return _Pipe()


class _FakeDb:
    async def execute(self, *_args, **_kwargs):
        return SimpleNamespace(
            mappings=lambda: self,
            all=lambda: [
                {"id": "msg-1", "content": "Hola"},
                {"id": "msg-2", "content": "Cuántos años tienes?"},
            ],
        )


@pytest.mark.asyncio
async def test_only_latest_epoch_replies_with_merged_text(monkeypatch):
    monkeypatch.setattr(
        "services.inbound_reply_coalescer.coalesce_debounce_seconds",
        lambda: 0.0,
    )
    redis = _FakeRedis()
    db = _FakeDb()

    first = await register_inbound_turn(
        redis,
        conversation_id="conv-1",
        message_id="msg-1",
        text_value="Hola",
        trace_id="trace-1",
    )
    second = await register_inbound_turn(
        redis,
        conversation_id="conv-1",
        message_id="msg-2",
        text_value="Cuántos años tienes?",
        trace_id="trace-2",
    )

    async def _noop_sleep(_seconds: float):
        return None

    follower = await finalize_coalesced_inbound_turn(
        redis,
        db,
        conversation_id="conv-1",
        message_id="msg-1",
        text_value="Hola",
        trace_id="trace-1",
        registration=first,
        sleep=_noop_sleep,
    )
    leader = await finalize_coalesced_inbound_turn(
        redis,
        db,
        conversation_id="conv-1",
        message_id="msg-2",
        text_value="Cuántos años tienes?",
        trace_id="trace-2",
        registration=second,
        sleep=_noop_sleep,
    )

    assert follower.should_reply is False
    assert leader.should_reply is True
    assert leader.merged_text == "Hola\nCuántos años tienes?"
    assert leader.message_count == 2
    assert leader.trigger_message_id == "msg-2"


def test_merge_coalesced_user_text_deduplicates_identical_lines():
    merged = merge_coalesced_user_text(["Hola", "Hola", "Cuántos años tienes?"])
    assert merged == "Hola\nCuántos años tienes?"
