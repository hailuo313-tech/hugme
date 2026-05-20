#!/usr/bin/env python3
"""J-03: dashboard integration smoke (C-10)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.dashboard_integration import (  # noqa: E402
    integration_contract,
    sort_conversations_for_dashboard,
)

FIXTURES = ROOT / "fixtures" / "j03_dashboard_smoke.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "J03_DASHBOARD_SMOKE_REPORT.md"


def run_smoke(*, write_report: Path | None) -> int:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    passed = 0
    rows: list[dict] = []
    for case in data["sort_cases"]:
        got = sort_conversations_for_dashboard(case["input"])
        first = got[0]["conversation_id"] if got else None
        ok = first == case["expect_first"]
        rows.append(
            {
                "id": case["id"],
                "title": case["title"],
                "expect_first": case["expect_first"],
                "got_first": first,
                "pass": ok,
            }
        )
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} {case['title']}")
        if ok:
            passed += 1

    total = len(data["sort_cases"])
    contract = integration_contract()
    print(f"\nJ-03 smoke: {passed}/{total} sort cases")
    print(f"Takeover SLA: {contract['takeover_sla_ms']} ms")
    print(f"Checklist items: {len(contract['checklist_ids'])}")

    if write_report:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(_render_report(rows, passed, total, contract), encoding="utf-8")
        print(f"Report: {write_report}")

    return 0 if passed == total else 1


def _render_report(rows: list[dict], passed: int, total: int, contract: dict) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# J-03 看板联调冒烟报告",
        "",
        f"**生成时间：** {ts}  ",
        f"**排序用例：** {passed}/{total}  ",
        f"**接管 SLA：** {contract['takeover_sla_ms']} ms  ",
        "",
        "## 明细",
        "",
        "| ID | 场景 | 结果 |",
        "|----|------|------|",
    ]
    for r in rows:
        mark = "PASS" if r["pass"] else "**FAIL**"
        lines.append(f"| {r['id']} | {r['title']} | {mark} |")
    lines.extend(["", "## 结论", ""])
    if passed == total:
        lines.append("**通过** — 排序契约 OK；录屏与人工签字见 C10 清单。")
    else:
        lines.append("**未通过** — 修复排序或夹具。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="J-03 dashboard smoke")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    report = None if args.no_report else Path(args.report)
    raise SystemExit(run_smoke(write_report=report))


if __name__ == "__main__":
    main()
