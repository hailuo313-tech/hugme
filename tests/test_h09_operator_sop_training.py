from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAINING_PATH = ROOT / "config" / "h09_operator_sop_training.json"


def _load_training() -> dict:
    return json.loads(TRAINING_PATH.read_text(encoding="utf-8"))


def test_h09_training_is_approved() -> None:
    training = _load_training()

    assert training["task_id"] == "H-09"
    assert training["status"] == "approved"
    assert training["approved_on"] == "2026-05-20"


def test_attendance_rate_is_100_percent() -> None:
    training = _load_training()
    roster = training["training_roster"]

    assert roster["required_operator_count"] > 0
    assert roster["attended_operator_count"] == roster["required_operator_count"]
    assert roster["attendance_rate"] == 1.0
    assert len(roster["operators"]) == roster["required_operator_count"]


def test_all_operators_completed_and_passed() -> None:
    training = _load_training()
    passing_score = training["assessment"]["passing_score_min"]

    for operator in training["training_roster"]["operators"]:
        assert operator["training_status"] == "completed"
        assert operator["assessment_status"] == "passed"
        assert operator["score"] >= passing_score
        assert operator["signed_at"]


def test_required_modules_cover_handoff_safety_quality_and_beta() -> None:
    training = _load_training()
    titles = "\n".join(module["title"].lower() for module in training["training_modules"])

    assert "handoff" in titles
    assert "safety" in titles
    assert "quality" in titles
    assert "beta" in titles
    assert all(module["required"] for module in training["training_modules"])


def test_assessment_covers_practical_operator_checks() -> None:
    training = _load_training()
    checks = set(training["assessment"]["practical_checks"])

    assert {
        "login_and_profile_check",
        "waiting_operator_filter",
        "lock_reply_return_ai_flow",
        "manual_premium_boundary_for_as",
        "b_level_ai_assisted_observation",
        "crisis_or_minor_escalation",
        "quality_score_submission",
        "handoff_stale_over_15m_detection",
    } <= checks


def test_operating_sla_protects_beta_handoff() -> None:
    training = _load_training()
    sla = training["operating_sla"]

    assert sla["waiting_operator_first_touch_seconds"] <= 180
    assert sla["human_locked_stale_minutes"] == 15
    assert sla["p0_immediate_escalation"] is True
    assert "payment details" in sla["privacy_rule"]
