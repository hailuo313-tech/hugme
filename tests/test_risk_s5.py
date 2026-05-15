"""RISK-S5：S5 阶段、通知门控、handoff 恢复规则。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.risk_s5 import (
    S5Phase,
    S5Restrictions,
    S5_CARE_NOTIFICATION_TYPE,
    compute_s5_phase,
    handoff_return_ai_block_reason,
    load_s5_restrictions,
    notification_block_reason,
    relationship_stage_is_s5,
)


def test_relationship_stage_is_s5():
    assert relationship_stage_is_s5({"relationship_stage": "S5"})
    assert not relationship_stage_is_s5({"relationship_stage": "S2"})


def test_compute_s5_phase_boundaries():
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    assert compute_s5_phase(t0, t0 + timedelta(hours=24)) == S5Phase.ACUTE
    assert compute_s5_phase(t0, t0 + timedelta(hours=48)) == S5Phase.CARE_WINDOW
    assert compute_s5_phase(t0, t0 + timedelta(hours=60)) == S5Phase.CARE_WINDOW
    assert compute_s5_phase(t0, t0 + timedelta(hours=80)) == S5Phase.STABILIZATION
    assert compute_s5_phase(t0, t0 + timedelta(days=7)) == S5Phase.RECOVERY_ELIGIBLE


def test_notification_blocks_marketing_and_care_window():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    acute = S5Restrictions(
        active=True,
        phase=S5Phase.ACUTE,
        entered_at=now,
        hours_since_entry=1.0,
    )
    assert notification_block_reason(acute, "silent_reactivation")
    assert notification_block_reason(acute, S5_CARE_NOTIFICATION_TYPE)

    care = S5Restrictions(
        active=True,
        phase=S5Phase.CARE_WINDOW,
        entered_at=now - timedelta(hours=50),
        hours_since_entry=50.0,
    )
    assert notification_block_reason(care, S5_CARE_NOTIFICATION_TYPE) is None
    assert notification_block_reason(care, "silent_reactivation")


def test_handoff_return_ai_rules():
    now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    stab = S5Restrictions(
        active=True,
        phase=S5Phase.STABILIZATION,
        entered_at=now - timedelta(days=3),
        hours_since_entry=72.0,
    )
    assert handoff_return_ai_block_reason(stab, allow_upsell=False)
    assert handoff_return_ai_block_reason(stab, allow_upsell=True)

    rec = S5Restrictions(
        active=True,
        phase=S5Phase.RECOVERY_ELIGIBLE,
        entered_at=now - timedelta(days=8),
        hours_since_entry=192.0,
    )
    assert handoff_return_ai_block_reason(rec, allow_upsell=False) is None
    assert handoff_return_ai_block_reason(rec, allow_upsell=True)


@pytest.mark.asyncio
async def test_load_s5_restrictions_uses_crisis_event_timestamp():
    db = MagicMock()
    entered = datetime(2026, 5, 1, 0, 0, 0)
    db.execute = AsyncMock(
        return_value=MagicMock(fetchone=lambda: (entered,))
    )
    res = await load_s5_restrictions(
        db,
        user_id="u1",
        profile={"relationship_stage": "S5"},
        now=datetime(2026, 5, 4, 1, 0, 0),  # 73h after crisis → stabilization
    )
    assert res.active
    assert res.phase == S5Phase.STABILIZATION
    assert res.entered_at == entered
