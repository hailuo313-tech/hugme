from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL_PATH = ROOT / "config" / "h07_week9_cd_canary_approval.json"


def _load_approval() -> dict:
    return json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))


def test_h07_approval_is_signed_for_week9() -> None:
    approval = _load_approval()

    assert approval["task_id"] == "H-07"
    assert approval["status"] == "approved"
    assert approval["approved_on"] == "2026-05-20"
    assert approval["approved_by"] == "release_owner"
    assert "pending_final_review" not in approval["approved_by"]
    assert approval["canary_window"]["week"] == "Week9"


def test_canary_includes_only_c_and_d_levels() -> None:
    approval = _load_approval()
    policy = approval["traffic_policy"]

    assert policy["included_levels"] == ["C", "D"]
    assert policy["excluded_levels"] == ["S", "A", "B"]
    assert policy["included_chat_routes"] == ["ai_auto"]
    assert "manual_premium" in policy["excluded_chat_routes"]
    assert "ai_assisted" in policy["excluded_chat_routes"]
    assert policy["operator_override_required_for_excluded_levels"] is True


def test_entry_gates_cover_smoke_health_backup_and_admin() -> None:
    approval = _load_approval()
    gates = "\n".join(approval["entry_gates"]).lower()

    assert "c-08" in gates
    assert "j-01" in gates
    assert "/health/detail" in gates
    assert "backup" in gates
    assert "admin conversation list" in gates


def test_pause_conditions_block_wrong_level_cutover() -> None:
    approval = _load_approval()
    pause = "\n".join(approval["pause_conditions"]).lower()

    assert "assistant replies fail" in pause
    assert "s, a, or b level user" in pause
    assert "data-loss" in pause
    assert "privacy exposure" in pause


def test_rollback_plan_has_disable_and_resume_conditions() -> None:
    approval = _load_approval()
    rollback = approval["rollback_plan"]

    assert "Disable" in rollback["primary_action"]
    assert rollback["evidence_to_preserve"]
    resume = "\n".join(rollback["resume_conditions"]).lower()
    assert "/health/detail" in resume
    assert "onboarding" in resume
    assert "admin conversation list" in resume
