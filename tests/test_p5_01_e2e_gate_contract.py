from __future__ import annotations

from pathlib import Path

from scripts.check_p5_01_e2e_gate import RUNNER, WORKFLOW, validate_contract


def test_p5_01_nightly_gate_uses_runner_that_enables_e2e_flag() -> None:
    issues = validate_contract(
        WORKFLOW.read_text(encoding="utf-8"),
        RUNNER.read_text(encoding="utf-8"),
    )

    assert issues == []


def test_p5_01_contract_fails_if_runner_does_not_enable_flag() -> None:
    workflow = "name: p5-01-e2e-mtproto-flow\nrun: bash scripts/e2e/run_p5_01.sh\ndocker compose up -d postgres redis\ndocker compose up -d --build api\n"
    runner = f"pytest {Path('tests/test_p5_01_e2e_mtproto_ai_archive.py')}\n"

    issues = validate_contract(workflow, runner)

    assert "P5-01 runner must enable RUN_P5_01_E2E=1" in issues
