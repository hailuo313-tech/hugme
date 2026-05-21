from __future__ import annotations

import json
from pathlib import Path

from services.regression_gate import (
    DEFAULT_INTENT_REGRESSION_PATH,
    DEFAULT_LEVEL_REGRESSION_PATH,
    run_regression_gate,
    run_intent_regression,
    run_level_regression,
)


ROOT = Path(__file__).resolve().parents[1]
BUSINESS_FLOW_PATH = ROOT / "docs" / "product" / "business-flow.html"


def test_p5_03_level_regression_set_is_maintained_and_zero_failure() -> None:
    cases = json.loads(DEFAULT_LEVEL_REGRESSION_PATH.read_text(encoding="utf-8"))
    result = run_level_regression()

    assert len(cases) >= 20
    assert result.total == len(cases)
    assert result.failed == 0, result.model_dump()


def test_p5_03_intent_regression_set_is_maintained_and_zero_failure() -> None:
    cases = json.loads(DEFAULT_INTENT_REGRESSION_PATH.read_text(encoding="utf-8"))
    result = run_intent_regression()

    assert len(cases) >= 50
    assert result.total == len(cases)
    assert result.failed == 0, result.model_dump()


def test_p5_03_combined_regression_gate_has_zero_failures() -> None:
    result = run_regression_gate()
    payload = result.model_dump()

    assert payload["task_id"] == "P5-03"
    assert payload["total"] >= 70
    assert payload["failed"] == 0, payload
    assert payload["status"] == "passed"


def test_p5_03_business_flow_marked_done() -> None:
    src = BUSINESS_FLOW_PATH.read_text(encoding="utf-8")
    line = next(line for line in src.splitlines() if 'id:"P5-03"' in line)

    assert "baseline:true" in line
