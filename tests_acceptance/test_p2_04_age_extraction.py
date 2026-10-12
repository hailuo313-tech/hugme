"""P2-04: age extraction writes only high-confidence profile values."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.age_extraction import (
    AGE_PROFILE_KEY,
    AgeExtractionResult,
    decide_age_profile_write,
    extract_age_with_llm,
    maybe_extract_and_write_age,
    parse_age_extraction_payload,
)


def test_parse_json_payload_from_llm_fence():
    result = parse_age_extraction_payload(
        '```json\n{"age": 29, "confidence": 0.92, "reason": "direct"}\n```'
    )

    assert result.age == 29
    assert result.confidence == 0.92
    assert result.reason == "direct"


def test_low_confidence_is_not_writable():
    decision = decide_age_profile_write(
        AgeExtractionResult(age=24, confidence=0.62, reason="maybe")
    )

    assert decision.should_write is False
    assert decision.reason == "low_confidence"


def test_out_of_range_age_is_removed_before_write_decision():
    result = parse_age_extraction_payload({"age": 9, "confidence": 0.99})
    decision = decide_age_profile_write(result)

    assert result.age is None
    assert decision.should_write is False
    assert decision.reason == "missing_age"


@pytest.mark.asyncio
async def test_extract_age_with_llm_uses_json_result():
    async def fake_chat(**kwargs):
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_tokens"] == 120
        assert kwargs["messages"][0]["role"] == "system"
        return SimpleNamespace(
            content='{"age": 31, "confidence": 0.88, "reason": "explicit"}',
            error=None,
        )

    result = await extract_age_with_llm(
        content="I am 31 years old.",
        trace_id="tr",
        chat_fn=fake_chat,
    )

    assert result.age == 31
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_high_confidence_writes_profile_preferences():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    async def fake_chat(**kwargs):
        return SimpleNamespace(
            content='{"age": 28, "confidence": 0.93, "reason": "explicit"}',
            error=None,
        )

    decision = await maybe_extract_and_write_age(
        db=db,
        user_id="00000000-0000-0000-0000-000000000001",
        content="I am 28.",
        trace_id="tr",
        chat_fn=fake_chat,
    )

    assert decision.should_write is True
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()
    sql = str(db.execute.await_args.args[0])
    params = db.execute.await_args.args[1]
    assert "jsonb_set" in sql
    assert AGE_PROFILE_KEY in params["path"]
    assert '"age": 28' in params["payload"]
    assert '"confidence": 0.93' in params["payload"]


@pytest.mark.asyncio
async def test_low_confidence_does_not_write_profile():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    async def fake_chat(**kwargs):
        return SimpleNamespace(
            content='{"age": 28, "confidence": 0.4, "reason": "ambiguous"}',
            error=None,
        )

    decision = await maybe_extract_and_write_age(
        db=db,
        user_id="00000000-0000-0000-0000-000000000001",
        content="People say I look 28.",
        trace_id="tr",
        chat_fn=fake_chat,
    )

    assert decision.should_write is False
    assert decision.reason == "low_confidence"
    db.execute.assert_not_called()
    db.commit.assert_not_called()
