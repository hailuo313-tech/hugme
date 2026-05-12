"""D2-2 单元测试：app/services/llm_orchestrator.py

覆盖：
- happy path：LLM 返回非空 content，orchestrator 透传。
- 上游异常 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLMResult.error 非空 + 未启用 fallback → 抛 LLMOrchestratorError。
- LLM 返回空 content → 视为失败。
- 启用 LLM_ECHO_FALLBACK → 失败时回退为 "echo: <user_text>"。

所有外部 IO（实际的 LLM HTTP 调用）通过 monkeypatch 拦截。
"""
from __future__ import annotations

import importlib
from typing import Any

import pytest


# ── fixtures ───────────────────────────────────────────

@pytest.fixture
def llm_orchestrator():
    """每个测试都重新 import，避免 monkeypatch 残留。"""
    import services.llm_orchestrator as mod  # type: ignore

    importlib.reload(mod)
    return mod


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
