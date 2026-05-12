"""D2-2 / D2-2.1 单元测试：app/services/llm_orchestrator.py

覆盖：
- happy path：LLM 返回非空 content，orchestrator 透传。
- 上游异常 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLMResult.error 非空 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLM 返回空 content → 视为失败。
- 启用 LLM_ECHO_FALLBACK → 失败时回退为 "echo: <user_text>"。
- D2-2.1：传入 redis 客户端 → 历史消息被拼进 messages，角色映射正确，
  最末一条（=当前消息）被丢弃。
- D2-2.1：redis.lrange 抛异常 → 仍能完成调用，仅记录 warning。
- D2-2.1：history_limit=0 / redis=None → 不读取历史。

所有外部 IO（实际的 LLM HTTP 调用 + Redis）通过 monkeypatch / fake 对象拦截。
"""
from __future__ import annotations

import importlib
import json
from typing import Any

import pytest


# ── fixtures ───────────────────────────────────────────

@pytest.fixture
def llm_orchestrator():
    """每个测试都重新 import，避免 monkeypatch 残留。"""
    import services.llm_orchestrator as mod  # type: ignore

    importlib.reload(mod)
    return mod


class _FakeRedis:
    """轻量 redis 替身，只实现 orchestrator 用到的 lrange。"""

    def __init__(self, items: list[str] | Exception):
        self._items = items

    async def lrange(self, key: str, start: int, end: int):
        if isinstance(self._items, Exception):
            raise self._items
        # 模拟 Redis lrange(-N, -1) 行为：返回最后 |start| 条
        items = self._items
        if start < 0:
            start_idx = max(0, len(items) + start)
        else:
            start_idx = start
        if end < 0:
            end_idx = len(items) + end + 1
        else:
            end_idx = end + 1
        return items[start_idx:end_idx]


def _ctx_entry(role: str, content: str, msg_id: str = "m") -> str:
    return json.dumps(
        {"role": role, "content": content, "msg_id": msg_id, "ts": 1},
        ensure_ascii=False,
    )


class _LLMResultStub:
    """轻量替身，模拟 services.llm.LLMResult 的字段。"""

    def __init__(
        self,
        content: str = "",
        model_used: str = "test/model",
        usage: dict[str, Any] | None = None,
        latency_ms: float = 12.3,
        fallback_used: bool = False,
        error: str | None = None,
    ) -> None:
        self.content = content
        self.model_used = model_used
        self.usage = usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 9}
        self.latency_ms = latency_ms
        self.fallback_used = fallback_used
        self.error = error


# ── tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_returns_llm_content(monkeypatch, llm_orchestrator):
    """LLM 返回非空 content → orchestrator 透传返回值；trace_id 透传到 chat()。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        captured["trace_id"] = trace_id
        return _LLMResultStub(content="hello from llm")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    reply = await llm_orchestrator.generate_reply(
        user_id="user-1",
        conversation_id="conv-1",
        user_text="hi",
        trace_id="trace-happy",
    )

    assert reply == "hello from llm"
    assert captured["trace_id"] == "trace-happy"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_upstream_exception_without_fallback(monkeypatch, llm_orchestrator):
    """上游 chat() 抛异常 + 未启用 fallback → 抛 LLMOrchestratorError。"""

    async def boom(*, messages, trace_id, **_kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", boom)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="hi",
            trace_id="trace-fail",
        )


@pytest.mark.asyncio
async def test_llm_result_error_without_fallback(monkeypatch, llm_orchestrator):
    """LLMResult.error 非空（llm.chat 内部兜底）→ orchestrator 视为失败。"""

    async def returns_error(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(
            content="[兜底文案]",
            error="primary=timeout; fallback=5xx",
            fallback_used=True,
        )

    monkeypatch.setattr(llm_orchestrator, "llm_chat", returns_error)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="hello",
            trace_id="trace-err",
        )


@pytest.mark.asyncio
async def test_empty_content_without_fallback(monkeypatch, llm_orchestrator):
    """LLM 返回空 content → 视为失败。"""

    async def empty(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="", error=None)

    monkeypatch.setattr(llm_orchestrator, "llm_chat", empty)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    with pytest.raises(llm_orchestrator.LLMOrchestratorError):
        await llm_orchestrator.generate_reply(
            user_id="u",
            conversation_id="c",
            user_text="ok",
            trace_id="trace-empty",
        )


@pytest.mark.asyncio
async def test_fallback_returns_echo_when_enabled(monkeypatch, llm_orchestrator):
    """启用 LLM_ECHO_FALLBACK → LLM 失败时回退为 'echo: <user_text>'。"""

    async def boom(*, messages, trace_id, **_kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", boom)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", True)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="ping",
        trace_id="trace-fallback",
    )

    assert reply == "echo: ping"


@pytest.mark.asyncio
async def test_fallback_on_llm_result_error_when_enabled(monkeypatch, llm_orchestrator):
    """启用 LLM_ECHO_FALLBACK + LLMResult.error 非空 → 也走 echo 回退。"""

    async def with_error(*, messages, trace_id, **_kwargs):
        return _LLMResultStub(content="ignored", error="upstream timeout")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", with_error)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", True)

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="pong",
        trace_id="trace-fallback-2",
    )

    assert reply == "echo: pong"


# ── D2-2.1：Redis 短期上下文 ─────────────────────────────

@pytest.mark.asyncio
async def test_history_from_redis_is_inserted_between_system_and_user(
    monkeypatch, llm_orchestrator
):
    """传入 redis 时：ctx 里的历史被拼进 messages，最末一条丢弃，角色映射正确。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    # ctx 中 4 条：3 条真历史 + 最末一条 = 当前用户消息（应被丢弃）
    redis = _FakeRedis(
        [
            _ctx_entry("user", "我叫小海"),
            _ctx_entry("assistant", "你好小海"),
            _ctx_entry("bot", "今天怎么样？"),   # 'bot' 应映射为 'assistant'
            _ctx_entry("user", "我今天有点累"),  # 最末一条 = 当前消息
        ]
    )

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="我今天有点累",
        trace_id="trace-ctx",
        redis=redis,
    )

    assert reply == "ok"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "我今天有点累"}
    history = msgs[1:-1]
    assert history == [
        {"role": "user", "content": "我叫小海"},
        {"role": "assistant", "content": "你好小海"},
        {"role": "assistant", "content": "今天怎么样？"},
    ]


@pytest.mark.asyncio
async def test_redis_lrange_failure_does_not_block(monkeypatch, llm_orchestrator):
    """redis.lrange 抛异常 → orchestrator 仍能返回回复，history 视为空。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="still ok")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    redis = _FakeRedis(RuntimeError("redis down"))

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hi",
        trace_id="trace-redis-down",
        redis=redis,
    )

    assert reply == "still ok"
    # 没有历史，messages 只有 system + 当前 user
    assert captured["messages"] == [
        {"role": "system", "content": llm_orchestrator.DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_history_limit_zero_skips_redis(monkeypatch, llm_orchestrator):
    """history_limit=0 → 不调用 redis.lrange。"""
    captured: dict[str, Any] = {}

    async def fake_chat(*, messages, trace_id, **_kwargs):
        captured["messages"] = messages
        return _LLMResultStub(content="no-history")

    monkeypatch.setattr(llm_orchestrator, "llm_chat", fake_chat)
    monkeypatch.setattr(llm_orchestrator.settings, "LLM_ECHO_FALLBACK", False)

    class _NoLrangeRedis:
        async def lrange(self, *_a, **_k):
            raise AssertionError("lrange should not be called when history_limit=0")

    reply = await llm_orchestrator.generate_reply(
        user_id="u",
        conversation_id="c",
        user_text="hello",
        trace_id="trace-nohist",
        redis=_NoLrangeRedis(),
        history_limit=0,
    )

    assert reply == "no-history"
    assert captured["messages"] == [
        {"role": "system", "content": llm_orchestrator.DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "hello"},
    ]
