from __future__ import annotations

import pytest

from services.conversation_context import append_conversation_context
from services.llm_orchestrator import _load_recent_context


class FakeLog:
    def bind(self, **_kwargs):
        return self

    def warning(self, *_args, **_kwargs) -> None:
        return None


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


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.lrange_calls: list[tuple[str, int, int]] = []

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def lrange(self, key: str, start: int, end: int):
        self.lrange_calls.append((key, start, end))
        items = self.lists.get(key, [])
        start_idx = max(0, len(items) + start) if start < 0 else start
        end_idx = len(items) + end + 1 if end < 0 else end + 1
        return items[start_idx:end_idx]


@pytest.mark.asyncio
async def test_llm_context_loader_reads_conv_user_context_first() -> None:
    redis = FakeRedis()
    await append_conversation_context(redis, user_id="u1", role="user", content="previous")
    await append_conversation_context(redis, user_id="u1", role="assistant", content="reply")
    await append_conversation_context(redis, user_id="u1", role="user", content="current")

    history = await _load_recent_context(
        redis=redis,
        user_id="u1",
        conversation_id="c1",
        history_limit=10,
        log=FakeLog(),
    )

    assert history == [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "reply"},
    ]
    assert redis.lrange_calls[0][0] == "conv:u1"


@pytest.mark.asyncio
async def test_llm_context_loader_falls_back_to_legacy_ctx_when_conv_empty() -> None:
    redis = FakeRedis()
    redis.lists["ctx:c1"] = [
        '{"role":"user","content":"legacy previous","msg_id":"m1","ts":1}',
        '{"role":"user","content":"current","msg_id":"m2","ts":2}',
    ]

    history = await _load_recent_context(
        redis=redis,
        user_id="u1",
        conversation_id="c1",
        history_limit=10,
        log=FakeLog(),
    )

    assert history == [{"role": "user", "content": "legacy previous"}]
    assert redis.lrange_calls[0][0] == "conv:u1"
    assert redis.lrange_calls[1][0] == "ctx:c1"
