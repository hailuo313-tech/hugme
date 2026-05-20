#!/usr/bin/env python3
"""C-14: pre-launch architecture and cursor deliverable audit."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.prelaunch_integration import (  # noqa: E402
    BASELINE_TASK_IDS,
    CANONICAL_PATHS,
    CURSOR_DELIVERABLES,
    FORBIDDEN_TOP_LEVEL_DIRS,
    PR_GATE_JOBS,
    REQUIRED_COMPOSE_SERVICES,
    integration_contract,
)

REPORT = ROOT / "docs" / "reports" / "C14_PRELAUNCH_AUDIT_REPORT.md"
BF = ROOT / "docs" / "product" / "business-flow.html"


def main() -> int:
    failures: list[str] = []

    for rel in CANONICAL_PATHS:
        p = ROOT / rel
        if rel.endswith("/"):
            if not p.is_dir():
                failures.append(f"missing directory: {rel}")
        elif not p.is_file() and not p.is_dir():
            failures.append(f"missing path: {rel}")

    for name in FORBIDDEN_TOP_LEVEL_DIRS:
        if (ROOT / name).exists():
            failures.append(f"forbidden legacy top-level dir present: {name}/")

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for svc in REQUIRED_COMPOSE_SERVICES:
        if not re.search(rf"^\s{{2}}{re.escape(svc)}:", compose, re.MULTILINE):
            failures.append(f"docker-compose.yml missing service: {svc}")

    pr = (ROOT / ".github/workflows/pr-required-gates.yml").read_text(encoding="utf-8")
    for job in PR_GATE_JOBS:
        if job not in pr:
            failures.append(f"pr-required-gates missing job: {job}")

    admin_cfg = (ROOT / "admin/next.config.js").read_text(encoding="utf-8")
    if 'basePath: "/admin"' not in admin_cfg:
        failures.append("admin next.config.js missing basePath /admin")

    for task_id, paths in CURSOR_DELIVERABLES.items():
        for rel in paths:
            if not (ROOT / rel).is_file():
                failures.append(f"{task_id} missing deliverable: {rel}")

    stability = ROOT / "fixtures/c12_nightly_stability.json"
    if stability.is_file():
        data = json.loads(stability.read_text(encoding="utf-8"))
        if not data.get("stability_met"):
            failures.append("c12_nightly_stability.json stability_met is false")
    else:
        failures.append("missing fixtures/c12_nightly_stability.json")

    bf = BF.read_text(encoding="utf-8") if BF.is_file() else ""
    for tid in BASELINE_TASK_IDS:
        if not re.search(rf'id:"{re.escape(tid)}"[^}}]*baseline:true', bf):
            failures.append(f"business-flow missing baseline:true for {tid}")

    # C-13 dashboard panels (bundled in this PR)
    dash = ROOT / "monitoring/grafana-dashboard-eris-mvp.json"
    if dash.is_file():
        blob = dash.read_text(encoding="utf-8")
        for panel in ("LLM Request Rate", "LLM p95 Latency"):
            if panel not in blob:
                failures.append(f"grafana dashboard missing panel: {panel}")
    else:
        failures.append("missing monitoring/grafana-dashboard-eris-mvp.json")

    if not (ROOT / "docs/C14_PRELAUNCH_ISSUES.md").is_file():
        failures.append("missing docs/C14_PRELAUNCH_ISSUES.md")

    contract = integration_contract()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-14 Pre-launch audit (machine)",
        "",
        f"- canonical paths checked: **{len(CANONICAL_PATHS)}**",
        f"- cursor deliverable groups: **{len(CURSOR_DELIVERABLES)}**",
        f"- baseline tasks in business-flow: **{len(BASELINE_TASK_IDS)}**",
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
    lines.append("**PASS** — architecture layout consistent; cursor deliverables present; no blocking failures.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[PASS] C-14 pre-launch audit")
    print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
