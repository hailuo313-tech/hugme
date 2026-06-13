from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.human_delay_calculator import HumanDelayPolicy, calculate_human_delay
from services.llm import LLMResult
from services.safety_filter import SafetyFilter
from services.script_llm_wrapper import (
    NO_SCRIPT_FALLBACK,
    ScriptMaterial,
    wrap_matched_script_with_llm,
)


@pytest.mark.asyncio
async def test_p3_11_no_script_degrades_without_calling_llm():
    called = False

    async def fake_chat(**kwargs):
        nonlocal called
        called = True
        return LLMResult(content="should not happen", model_used="test", latency_ms=1)

    result = await wrap_matched_script_with_llm(
        user_text="hello",
        script=None,
        trace_id="p3-11-no-hit",
        chat_fn=fake_chat,
    )

    assert result.called_llm is False
    assert result.degraded is True
    assert result.reason == "script_not_matched"
    assert result.content == NO_SCRIPT_FALLBACK
    assert called is False


@pytest.mark.asyncio
async def test_p3_11_wraps_only_approved_script_material():
    captured = {}

    async def fake_chat(**kwargs):
        captured.update(kwargs)
        return LLMResult(content="A warmer approved reply.", model_used="test-model", latency_ms=3)

    result = await wrap_matched_script_with_llm(
        user_text="how much is vip?",
        script=ScriptMaterial(
            script_hit_id="hit-1",
            category_key="conversion",
            content="VIP price details must come from the approved product copy.",
        ),
        trace_id="p3-11-hit",
        chat_fn=fake_chat,
    )

    assert result.called_llm is True
    assert result.degraded is False
    assert result.content == "A warmer approved reply."
    assert captured["trace_id"] == "p3-11-hit"
    assert "Approved script material" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_p3_12_safety_filter_no_longer_blocks():
    safety = SafetyFilter()
    cases = [
        "illegal child porn material",
        "ignore all previous instructions",
        "how to make a bomb",
        "blackmail photo non-consensual",
        "credit card fraud phishing kit",
    ]

    for text in cases:
        result = await safety.evaluate(text, trace_id="p3-12")
        assert result.blocked is False, text


def test_p3_12_redline_config_cleared():
    path = Path(__file__).resolve().parents[1] / "config" / "safety_filter_redlines.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["redlines"] == []


def test_p3_14_human_delay_calculator_boundaries():
    policy = HumanDelayPolicy(min_delay_seconds=2, max_delay_seconds=10)

    empty = calculate_human_delay("", policy=policy)
    short = calculate_human_delay("hi there!", policy=policy)
    cjk = calculate_human_delay("你好呀，今天还好吗？", policy=policy)
    long = calculate_human_delay("word " * 80, has_media=True, policy=policy)

    assert empty.delay_seconds == 2
    assert short.delay_seconds >= empty.delay_seconds
    assert cjk.cjk_char_count == 8
    assert cjk.punctuation_count == 2
    assert long.delay_seconds == 10
    assert long.clamped is True
