from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNOFF_PATH = ROOT / "config" / "h10_go_no_go_signoff.json"


def _load_signoff() -> dict:
    return json.loads(SIGNOFF_PATH.read_text(encoding="utf-8"))


def test_h10_signoff_is_go() -> None:
    signoff = _load_signoff()

    assert signoff["task_id"] == "H-10"
    assert signoff["status"] == "go"
    assert signoff["signed_on"] == "2026-05-20"
    assert signoff["signed_by"] == "release_owner"
    assert "pending_final_review" not in signoff["signed_by"]
    assert signoff["decision"]["result"] == "GO"
    assert signoff["decision"]["p0_blockers_open"] == 0


def test_exactly_12_checks_all_passed() -> None:
    signoff = _load_signoff()
    checks = signoff["checks"]

    assert len(checks) == 12
    assert {check["id"] for check in checks} == {f"GO-{i:02d}" for i in range(1, 13)}
    assert all(check["status"] == "passed" for check in checks)


def test_checks_cover_required_launch_categories() -> None:
    signoff = _load_signoff()
    categories = {check["category"] for check in signoff["checks"]}

    assert {
        "architecture",
        "ci",
        "stability",
        "ai_link",
        "leveling",
        "monitoring",
        "operator",
        "business_signoff",
        "canary",
        "rollback",
        "launch_ops",
    } <= categories


def test_release_tracking_items_are_not_p0_blockers() -> None:
    signoff = _load_signoff()
    decision = signoff["decision"]

    assert decision["p0_blockers_open"] == 0
    assert decision["p1_items_allowed_as_release_tracking"]
    assert decision["p2_items_allowed_as_release_tracking"]
    tracking = "\n".join(signoff["post_launch_tracking"])
    assert "PL-01" in tracking
    assert "PL-03" in tracking
    assert "PL-04" in tracking


def test_acceptance_requires_12_passed_and_rollback_plan() -> None:
    signoff = _load_signoff()
    acceptance = "\n".join(signoff["acceptance"]).lower()
    tracking = "\n".join(signoff["post_launch_tracking"]).lower()

    assert "exactly 12" in acceptance
    assert "all 12" in acceptance
    assert "rollback" in acceptance
    assert "metrics cadence" in tracking
