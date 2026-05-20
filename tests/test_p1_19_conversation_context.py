from __future__ import annotations

import json

import pytest

from services.conversation_context import (
    CONVERSATION_CONTEXT_MAX_MESSAGES,
    CONVERSATION_CONTEXT_TTL_SECONDS,
    append_conversation_context,
    conversation_context_key,
    load_conversation_context,
)


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.ops: list[tuple] = []

    def rpush(self, key: str, value: str) -> None:
        self.ops.append(("rpush", key, value))

    def ltrim(self, key: str, start: int, end: int) -> None:
        self.ops.append(("ltrim", key, start, end))

    def expire(self, key: str, ttl: int) -> None:
        self.ops.append(("expire", key, ttl))

    async def execute(self) -> None:
        for op in self.ops:
            if op[0] == "rpush":
                _, key, value = op
                self.redis.lists.setdefault(key, []).append(value)
            elif op[0] == "ltrim":
                _, key, start, end = op
                items = self.redis.lists.get(key, [])
                start_idx = max(0, len(items) + start) if start < 0 else start
                end_idx = len(items) + end + 1 if end < 0 else end + 1
                self.redis.lists[key] = items[start_idx:end_idx]
            elif op[0] == "expire":
                _, key, ttl = op
                self.redis.ttls[key] = ttl


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def lrange(self, key: str, start: int, end: int):
        items = self.lists.get(key, [])
        start_idx = max(0, len(items) + start) if start < 0 else start
        end_idx = len(items) + end + 1 if end < 0 else end + 1
        return items[start_idx:end_idx]


@pytest.mark.asyncio
async def test_append_context_uses_conv_user_key_and_retains_50_rounds() -> None:
    redis = FakeRedis()

    for i in range(105):
        await append_conversation_context(
            redis,
            user_id="u1",
            role="user" if i % 2 == 0 else "assistant",
            content=f"msg-{i}",
            msg_id=f"m{i}",
        )

    key = conversation_context_key("u1")
    assert key == "conv:u1"
    assert len(redis.lists[key]) == CONVERSATION_CONTEXT_MAX_MESSAGES
    assert redis.ttls[key] == CONVERSATION_CONTEXT_TTL_SECONDS
    first = json.loads(redis.lists[key][0])
    last = json.loads(redis.lists[key][-1])
    assert first["content"] == "msg-5"
    assert last["content"] == "msg-104"


@pytest.mark.asyncio
async def test_load_context_returns_recent_messages_for_llm() -> None:
    redis = FakeRedis()
    for role, content in [
        ("user", "old"),
        ("assistant", "older reply"),
        ("user", "recent question"),
        ("assistant", "recent answer"),
    ]:
        await append_conversation_context(redis, user_id="u1", role=role, content=content)

    history = await load_conversation_context(redis, user_id="u1", limit=3)

    assert history == [
        {"role": "assistant", "content": "older reply"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
    ]


@pytest.mark.asyncio
async def test_load_context_can_drop_latest_current_message() -> None:
    redis = FakeRedis()
    await append_conversation_context(redis, user_id="u1", role="user", content="previous")
    await append_conversation_context(redis, user_id="u1", role="assistant", content="reply")
    await append_conversation_context(redis, user_id="u1", role="user", content="current")

    history = await load_conversation_context(redis, user_id="u1", limit=10, drop_latest=True)

    assert history == [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "reply"},
    ]
