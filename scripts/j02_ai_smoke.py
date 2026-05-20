#!/usr/bin/env python3
"""J-02: AI pipeline smoke runner (C-08).

Loads fixtures/j02_ai_smoke.json, runs in-process pipeline stages with timing,
prints summary, optionally writes docs/reports/J02_AI_SMOKE_REPORT.md.

Exit 0 when all fixtures pass and each is within 8s budget.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.ai_pipeline_smoke import (  # noqa: E402
    LATENCY_BUDGET_MS,
    run_pipeline_case,
    result_to_dict,
)

FIXTURES_PATH = ROOT / "fixtures" / "j02_ai_smoke.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "J02_AI_SMOKE_REPORT.md"


def _load_fixtures(path: Path) -> tuple[int, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    budget = int(data.get("latency_budget_ms", LATENCY_BUDGET_MS))
    return budget, list(data["fixtures"])


def run_smoke(*, write_report: Path | None) -> int:
    budget_ms, fixtures = _load_fixtures(FIXTURES_PATH)
    rows: list[dict] = []
    passed = 0
    for fix in fixtures:
        res = run_pipeline_case(fix)
        row = result_to_dict(res)
        rows.append(row)
        ok = res.pass_case and res.within_budget
        if ok:
            passed += 1
        status = "PASS" if ok else "FAIL"
        print(
            f"[{status}] {res.id} {res.title} "
            f"outcome={res.outcome} total_ms={res.total_ms} budget={budget_ms}"
        )
        if not ok:
            print(f"       expect={res.expect}")
            print(f"       timings={res.timings_ms}")

    total = len(fixtures)
    print(f"\nJ-02 smoke: {passed}/{total} passed (latency budget {budget_ms} ms)")
    if write_report:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(_render_report(rows, passed, total, budget_ms), encoding="utf-8")
        print(f"Report: {write_report}")

    return 0 if passed == total else 1


def _render_report(rows: list[dict], passed: int, total: int, budget_ms: int) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# J-02 AI 全链路冒烟报告",
        "",
        f"**生成时间：** {ts}  ",
        f"**结果：** {passed}/{total} fixture 通过  ",
        f"**延迟预算：** {budget_ms} ms（含模拟 LLM 延迟）  ",
        f"**脚本：** `scripts/j02_ai_smoke.py`  ",
        f"**夹具：** `fixtures/j02_ai_smoke.json`  ",
        "",
        "## 汇总",
        "",
        "| 结果 | 数量 |",
        "|------|------|",
        f"| PASS | {passed} |",
        f"| FAIL | {total - passed} |",
        "",
        "## 明细",
        "",
        "| ID | 场景 | 结果 | outcome | total_ms | within_budget | level |",
        "|----|------|------|---------|----------|---------------|-------|",
    ]
    for r in rows:
        mark = "PASS" if r["pass"] and r["within_budget"] else "**FAIL**"
        lines.append(
            f"| {r['id']} | {r['title']} | {mark} | {r['outcome']} | {r['total_ms']} | "
            f"{r['within_budget']} | {r.get('level') or '—'} |"
        )
    lines.extend(["", "## 阶段耗时（示例首条 PASS）", ""])
    for r in rows:
        if r["pass"]:
            lines.append(f"- **{r['id']}**: `{r['timings_ms']}`")
            break
    lines.extend(["", "## 结论", ""])
    if passed == total:
        lines.append(
            f"**{passed}/{total} 通过** — 进程内 AI 链路满足 <{budget_ms}ms 预算，可进入 C-08 关口。"
        )
    else:
        lines.append("**未通过** — 修复链路或夹具期望后重跑。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="J-02 AI pipeline smoke")
    parser.add_argument(
        "--report",
        default=str(DEFAULT_REPORT),
        help="Markdown report path (default: docs/reports/J02_AI_SMOKE_REPORT.md)",
    )
    parser.add_argument("--no-report", action="store_true", help="Skip writing report file")
    args = parser.parse_args()
    report_path = None if args.no_report else Path(args.report)
    raise SystemExit(run_smoke(write_report=report_path))


if __name__ == "__main__":
    main()
