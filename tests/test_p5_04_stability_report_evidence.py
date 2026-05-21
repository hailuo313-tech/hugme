from __future__ import annotations

from pathlib import Path

from scripts.check_p5_04_stability_report import validate_report


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "websocket-stability.yml"


def _valid_report() -> dict:
    return {
        "report": {
            "duration_hours": 72.03,
            "zero_message_loss": True,
            "ping_success_rate": 100.0,
            "uptime_percentage": 99.99,
            "reconnect_count": 1,
            "message_stats": {"lost_count": 0},
        }
    }


def test_p5_04_accepts_72h_zero_loss_report() -> None:
    assert validate_report(_valid_report()) == []


def test_p5_04_rejects_1h_smoke_as_final_evidence() -> None:
    report = _valid_report()
    report["report"]["duration_hours"] = 1.0

    issues = validate_report(report)

    assert any("duration_hours must be" in issue for issue in issues)


def test_p5_04_rejects_message_loss() -> None:
    report = _valid_report()
    report["report"]["zero_message_loss"] = False
    report["report"]["message_stats"]["lost_count"] = 1

    issues = validate_report(report)

    assert "zero_message_loss must be true" in issues
    assert any("lost_count must be 0" in issue for issue in issues)


def test_p5_04_ci_defaults_to_72h_and_validates_archived_report() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "default: '72'" in text
    assert "TEST_DURATION_HOURS: ${{ github.event.inputs.duration_hours || '72' }}" in text
    assert "timeout-minutes: 4380" in text
    assert "scripts/check_p5_04_stability_report.py" in text
