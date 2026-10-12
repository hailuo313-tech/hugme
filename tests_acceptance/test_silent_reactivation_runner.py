"""D6-3 runner 单元测试：``services.silent_reactivation_runner.run_silent_reactivation_scan``。

策略：不连真 DB；把三个 helper（_fetch_candidates / _fetch_prior_tiers /
_insert_task_if_absent）整体 mock 掉，专注 runner 的分支组合逻辑。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import silent_reactivation_runner as runner_mod
from services.silent_reactivation import EligibilityResult
from services.silent_reactivation_runner import (
    ScanSummary,
    run_silent_reactivation_scan,
)


NOW = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)


def _candidate_row(user_id: str = "u-1", hours_ago: int = 30) -> dict:
    return {
        "id": user_id,
        "channel": "telegram",
        "status": "active",
        "notification_opt_in": True,
        "opt_out_marketing": False,
        "is_minor_suspected": False,
        "risk_level": "normal",
        "timezone": "UTC",
        "last_user_message_at": NOW - timedelta(hours=hours_ago),
        "open_handoff_count": 0,
        "has_memory_signal": False,
    }


def _ok_eligibility(tier: str = "D1") -> EligibilityResult:
    return EligibilityResult(
        ok=True,
        tier=tier,
        scheduled_at=NOW,
        dedupe_key=f"silent_reactivation:{tier}:2026-05-12",
        payload={"strategy": "silent_reactivation", "tier": tier, "dedupe_key": f"silent_reactivation:{tier}:2026-05-12"},
    )


def _skip_eligibility(reason: str = "opt_out_marketing") -> EligibilityResult:
    return EligibilityResult(ok=False, skip_reason=reason)


async def test_short_circuits_when_disabled():
    """flag=False → 立刻返回空 summary，不查 DB。"""
    db = MagicMock()
    db.execute = AsyncMock()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", False):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert isinstance(summary, ScanSummary)
    assert summary.candidates == 0
    assert summary.created == 0
    db.execute.assert_not_awaited()


async def test_no_candidates_returns_empty_summary():
    db = MagicMock()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[])
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.candidates == 0
    assert summary.created == 0
    assert summary.skipped == {}


async def test_happy_path_creates_task():
    db = MagicMock()
    cand = _candidate_row()
    fake_id = "task-uuid-1"
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", return_value=_ok_eligibility("D1")
    ), patch.object(
        runner_mod, "_insert_task_if_absent", AsyncMock(return_value=fake_id)
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.candidates == 1
    assert summary.created == 1
    assert summary.created_ids == [fake_id]
    assert summary.skipped == {}


async def test_skip_when_not_eligible():
    db = MagicMock()
    cand = _candidate_row()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", return_value=_skip_eligibility("opt_out_marketing")
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.candidates == 1
    assert summary.created == 0
    assert summary.skipped == {"opt_out_marketing": 1}


async def test_skip_when_evaluate_raises():
    db = MagicMock()
    cand = _candidate_row()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", side_effect=RuntimeError("boom")
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.candidates == 1
    assert summary.created == 0
    assert summary.skipped == {"evaluate_exception": 1}


async def test_skip_when_dedupe_collision():
    """_insert_task_if_absent 返回 None → duplicate_dedupe_key 计数。"""
    db = MagicMock()
    cand = _candidate_row()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", return_value=_ok_eligibility("D1")
    ), patch.object(
        runner_mod, "_insert_task_if_absent", AsyncMock(return_value=None)
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.created == 0
    assert summary.skipped == {"duplicate_dedupe_key": 1}


async def test_skip_when_insert_raises():
    db = MagicMock()
    cand = _candidate_row()
    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", return_value=_ok_eligibility("D1")
    ), patch.object(
        runner_mod, "_insert_task_if_absent", AsyncMock(side_effect=RuntimeError("db boom"))
    ):
        summary = await run_silent_reactivation_scan(db, now_utc=NOW)
    assert summary.created == 0
    assert summary.skipped == {"insert_exception": 1}


async def test_naive_last_message_converted_to_utc():
    """DB 取回的 last_user_message_at 是 naive datetime → evaluate_user 应拿到带 UTC tz 的值。"""
    db = MagicMock()
    cand = _candidate_row()
    cand["last_user_message_at"] = (NOW - timedelta(hours=30)).replace(tzinfo=None)

    seen: list[datetime | None] = []

    def _capture(*args, **kwargs):
        seen.append(kwargs.get("last_user_message_at"))
        return _ok_eligibility("D1")

    with patch.object(runner_mod.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        runner_mod, "_fetch_candidates", AsyncMock(return_value=[cand])
    ), patch.object(
        runner_mod, "_fetch_prior_tiers", AsyncMock(return_value=set())
    ), patch.object(
        runner_mod, "evaluate_user", side_effect=_capture
    ), patch.object(
        runner_mod, "_insert_task_if_absent", AsyncMock(return_value="id-1")
    ):
        await run_silent_reactivation_scan(db, now_utc=NOW)

    assert seen and seen[0] is not None
    assert seen[0].tzinfo == timezone.utc
