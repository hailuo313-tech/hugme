"""V001-P0-4 / D6-4: notification_sender_worker 纯函数与短路行为。"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from services.notification_sender_worker import (
    build_outbound_text,
    run_one_tick,
)
from core.config import settings


@pytest.mark.parametrize(
    "tier,snippet",
    [
        ("D1", "No rush"),
        ("D3", "pick up where you left off"),
        ("D7", "step back"),
        ("D9", "No rush"),  # unknown tier → D1 fallback
    ],
)
def test_build_outbound_silent_reactivation_tiers(tier: str, snippet: str):
    text = build_outbound_text(
        notification_type="silent_reactivation",
        payload={"tier": tier},
    )
    assert text is not None
    assert snippet in text


def test_build_outbound_s5_care():
    t = build_outbound_text(notification_type="s5_care_checkin", payload={})
    assert t is not None
    assert "checking in" in t.lower()


def test_build_outbound_unknown_returns_none():
    assert build_outbound_text(notification_type="marketing_blast", payload={}) is None


@pytest.mark.asyncio
async def test_run_one_tick_disabled_short_circuits():
    with patch.object(settings, "NOTIFICATION_SENDER_ENABLED", False):
        out = await run_one_tick(trace_id="t-test")
    assert out["claimed"] == 0
    assert out["sent"] == 0
    assert out["failed"] == 0
    assert out["skipped_no_lock"] == 0
