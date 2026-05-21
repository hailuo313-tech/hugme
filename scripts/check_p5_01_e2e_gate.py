#!/usr/bin/env python3
"""P5-01 E2E gate contract checker.

The heavy MTProto -> AI -> archive test is intentionally guarded by
RUN_P5_01_E2E for local pytest. This checker keeps the CI gate honest by
verifying the workflow uses the same runner script that enables the flag.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nightly-e2e-ci.yml"
RUNNER = ROOT / "scripts" / "e2e" / "run_p5_01.sh"
TEST_FILE = "tests/test_p5_01_e2e_mtproto_ai_archive.py"


def validate_contract(workflow_text: str, runner_text: str) -> list[str]:
    issues: list[str] = []

    if "p5-01-e2e-mtproto-flow" not in workflow_text:
        issues.append("nightly workflow is missing the P5-01 E2E job name")
    if "bash scripts/e2e/run_p5_01.sh" not in workflow_text:
        issues.append("nightly workflow must run scripts/e2e/run_p5_01.sh")
    if "docker compose up -d postgres redis" not in workflow_text:
        issues.append("nightly workflow must start postgres and redis")
    if "docker compose up -d --build api" not in workflow_text:
        issues.append("nightly workflow must start the API container")

    if "RUN_P5_01_E2E=1" not in runner_text:
        issues.append("P5-01 runner must enable RUN_P5_01_E2E=1")
    if TEST_FILE not in runner_text:
        issues.append(f"P5-01 runner must execute {TEST_FILE}")
    if "pytest" not in runner_text:
        issues.append("P5-01 runner must call pytest")

    return issues


def main() -> int:
    issues = validate_contract(
        WORKFLOW.read_text(encoding="utf-8"),
        RUNNER.read_text(encoding="utf-8"),
    )
    if issues:
        print("P5-01 E2E gate contract failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("P5-01 E2E gate contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
