from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL_PATH = ROOT / "config" / "h08_week10_11_bas_approval.json"


def _load_approval() -> dict:
    return json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))


def test_h08_approval_is_for_week10_11() -> None:
    approval = _load_approval()

    assert approval["task_id"] == "H-08"
    assert approval["status"] == "approved"
    assert approval["approved_on"] == "2026-05-20"
    assert approval["approved_by"] == "release_owner"
    assert "pending_final_review" not in approval["approved_by"]
    assert approval["dependency"]["task_id"] == "H-07"
    assert approval["canary_window"]["weeks"] == ["Week10", "Week11"]


def test_level_routes_match_approved_policy() -> None:
    approval = _load_approval()
    policy = approval["traffic_policy"]

    assert policy["continued_auto_levels"] == ["C", "D"]
    assert policy["observation_levels"] == ["B"]
    assert policy["handoff_levels"] == ["A", "S"]
    assert policy["level_routes"] == {
        "S": "manual_premium",
        "A": "manual_premium",
        "B": "ai_assisted",
        "C": "ai_auto",
        "D": "ai_auto",
    }


def test_b_observation_is_not_full_auto() -> None:
    approval = _load_approval()
    rules = "\n".join(approval["traffic_policy"]["b_observation_rules"]).lower()

    assert "ai-assisted" in rules
    assert "visible in admin" in rules
    assert "not approved for full ai_auto" in rules


def test_as_handoff_blocks_auto_cutover() -> None:
    approval = _load_approval()
    rules = "\n".join(approval["traffic_policy"]["as_handoff_rules"]).lower()
    pause = "\n".join(approval["pause_conditions"]).lower()

    assert "manual_premium" in rules
    assert "must not be included" in rules
    assert "a or s user is routed to ai_auto" in pause
    assert "b user is routed to ai_auto" in pause


def test_rollback_returns_to_h07_or_zero_traffic() -> None:
    approval = _load_approval()
    rollback = approval["rollback_plan"]

    assert "H-07 C/D-only policy" in rollback["primary_action"]
    assert "eligible traffic percent to 0" in rollback["secondary_action"]
    resume = "\n".join(rollback["resume_conditions"]).lower()
    assert "manual_premium" in resume
    assert "ai_assisted" in resume
