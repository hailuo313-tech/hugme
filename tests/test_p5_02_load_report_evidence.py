from __future__ import annotations

from pathlib import Path

from scripts.check_p5_02_load_report import validate_report


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "load-testing.yml"


def _valid_report() -> dict:
    return {
        "test_summary": {
            "concurrency": 1000,
            "acceptance_criteria": {
                "p99_threshold_ms": 500,
                "p99_actual_ms": 421.2,
                "passed": True,
            },
        },
        "overall_latency_ms": {"p99": 421.2},
        "endpoints": {"/health": {"p99": 30.0}},
    }


def test_p5_02_accepts_archived_1000_concurrency_report_under_500ms() -> None:
    assert validate_report(_valid_report()) == []


def test_p5_02_rejects_smaller_or_slow_report() -> None:
    report = _valid_report()
    report["test_summary"]["concurrency"] = 999
    report["test_summary"]["acceptance_criteria"]["p99_actual_ms"] = 500.0
    report["test_summary"]["acceptance_criteria"]["passed"] = False

    issues = validate_report(report)

    assert any("concurrency must be" in issue for issue in issues)
    assert any("p99 must be" in issue for issue in issues)
    assert "acceptance_criteria.passed must be true" in issues


def test_p5_02_ci_archives_and_validates_report() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "default: '1000'" in text
    assert "name: load-test-reports" in text
    assert "scripts/perf/reports/*.json" in text
    assert "scripts/check_p5_02_load_report.py" in text
