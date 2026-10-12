"""V001-P0-2：危机检测与 orchestrator 短路。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.crisis_intervention import (
    CRISIS_SAFETY_REPLY,
    detect_crisis_in_text,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I want to die", True),
        ("今天好想死啊", True),
        ("hello how are you", False),
        ("", False),
    ],
)
def test_detect_crisis_in_text(text: str, expected: bool):
    assert detect_crisis_in_text(text) is expected


@pytest.mark.asyncio
async def test_apply_crisis_protocol_writes():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    from services.crisis_intervention import apply_crisis_protocol

    result = await apply_crisis_protocol(
        db,
        user_id="u1",
        conversation_id="c1",
        user_text="I want to die",
        trigger_message_id="m1",
        trace_id="t1",
    )
    assert result.safety_reply == CRISIS_SAFETY_REPLY
    assert db.execute.await_count >= 4
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_reply_short_circuits_on_crisis():
    from services.llm_orchestrator import generate_reply

    db = MagicMock()
    with patch(
        "services.crisis_intervention.apply_crisis_protocol",
        new_callable=AsyncMock,
    ) as mock_apply:
        mock_apply.return_value = MagicMock(
            safety_reply="SAFE",
            risk_event_id="e1",
            handoff_task_id="h1",
        )
        out = await generate_reply(
            user_id="u1",
            conversation_id="c1",
            user_text="I want to die",
            trace_id="trace",
            db=db,
            trigger_message_id="m1",
        )
    assert out == "SAFE"
    mock_apply.assert_awaited_once()
