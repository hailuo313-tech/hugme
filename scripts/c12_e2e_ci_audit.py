#!/usr/bin/env python3
"""C-12: audit E2E/perf scripts and CI nightly wiring."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.e2e_ci_integration import (  # noqa: E402
    E2E_FULL_SCRIPT,
    E2E_SMOKE_SCRIPT,
    NIGHTLY_WORKFLOW,
    PERF_LOAD_SCRIPT,
    PR_WORKFLOW,
    integration_contract,
)

REPORT = ROOT / "docs" / "reports" / "C12_E2E_CI_AUDIT_REPORT.md"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _bash_n(rel: str) -> None:
    path = ROOT / rel
    subprocess.run(["bash", "-n", str(path)], check=True, cwd=ROOT)


def main() -> int:
    failures: list[str] = []
    run_sh = _read(E2E_FULL_SCRIPT)
    smoke_sh = _read(E2E_SMOKE_SCRIPT)
    perf_py = _read(PERF_LOAD_SCRIPT)

    for rel in (E2E_FULL_SCRIPT, E2E_SMOKE_SCRIPT, PERF_LOAD_SCRIPT, PR_WORKFLOW, NIGHTLY_WORKFLOW):
        if not (ROOT / rel).is_file():
            failures.append(f"missing file: {rel}")

    for needle in (
        "handoff lock API",
        "E2E_CHAT_ROUNDS",
        "E2E_SKIP_STRIPE",
        "POST /api/v1/handoff",
    ):
        if needle not in run_sh:
            failures.append(f"run.sh missing: {needle}")

    if "exec bash" not in smoke_sh or "E2E_CHAT_ROUNDS" not in smoke_sh:
        failures.append("smoke.sh must delegate to run.sh with smoke env")

    if "outside CI" not in perf_py and "outside ci" not in perf_py.lower():
        failures.append("perf script must document outside-CI scope")

    nightly = _read(NIGHTLY_WORKFLOW)
    if "schedule:" not in nightly or "e2e-smoke" not in nightly:
        failures.append("nightly workflow missing schedule or e2e-smoke job")

    pr = _read(PR_WORKFLOW)
    for job in ("admin-ci", "backend-ci", "ops-guard"):
        if job not in pr:
            failures.append(f"pr-required-gates missing job: {job}")

    try:
        _bash_n(E2E_FULL_SCRIPT)
        _bash_n(E2E_SMOKE_SCRIPT)
    except subprocess.CalledProcessError as exc:
        failures.append(f"bash -n failed: {exc}")

    contract = integration_contract()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-12 E2E/CI audit report (machine)",
        "",
        f"- checklist: **{len(contract['checklist_ids'])}** items",
        f"- nightly cron (UTC): `{contract['nightly_cron_utc']}`",
        f"- stability requirement: **{contract['nightly_stability_days']}** consecutive green runs",
        "",
        "## Contract",
        "",
        "```json",
        json.dumps(contract, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    if failures:
        lines.append("## Failures")
        lines.extend(f"- {f}" for f in failures)
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for f in failures:
            print(f"[FAIL] {f}", file=sys.stderr)
        return 1

    lines.append("## Result")
    lines.append("")
    lines.append("**PASS** — scripts and workflows present; bash -n OK.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[PASS] C-12 E2E/CI audit")
    print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
