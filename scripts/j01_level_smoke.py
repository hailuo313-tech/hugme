#!/usr/bin/env python3
"""J-01: level_engine smoke runner (C-06).

Loads fixtures/j01_level_smoke.json, runs calc_user_level with repo config,
prints a summary, optionally writes docs/reports/J01_LEVEL_SMOKE_REPORT.md.

Exit 0 when all fixtures pass (10/10).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.level_engine import UserLevelInput, calc_user_level, load_thresholds, load_t1_countries  # noqa: E402

FIXTURES_PATH = ROOT / "fixtures" / "j01_level_smoke.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "J01_LEVEL_SMOKE_REPORT.md"


def _load_fixtures(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["fixtures"])


def _run_case(fix: dict) -> tuple[bool, dict]:
    inp_raw = fix["input"]
    inp = UserLevelInput(
        profile_complete=bool(inp_raw["profile_complete"]),
        country_code=inp_raw.get("country_code"),
        lifetime_spend_usd=float(inp_raw.get("lifetime_spend_usd", 0)),
        vip_level=int(inp_raw.get("vip_level", 0)),
        operator_assigned_s=bool(inp_raw.get("operator_assigned_s", False)),
    )
    result = calc_user_level(inp)
    got = {
        "level": result.level,
        "chat_route": result.chat_route,
        "reason": result.reason,
        "country_tier": result.country_tier,
    }
    expect = fix["expect"]
    ok = got == expect
    return ok, {"id": fix["id"], "title": fix["title"], "expect": expect, "got": got, "input": inp_raw}


def run_smoke(*, write_report: Path | None) -> int:
    fixtures = _load_fixtures(FIXTURES_PATH)
    t1 = load_t1_countries()
    th = load_thresholds()
    rows: list[dict] = []
    passed = 0
    for fix in fixtures:
        ok, row = _run_case(fix)
        row["pass"] = ok
        rows.append(row)
        if ok:
            passed += 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {row['id']} {row['title']}")
        if not ok:
            print(f"       expect={row['expect']}")
            print(f"       got   ={row['got']}")

    total = len(fixtures)
    print(f"\nJ-01 smoke: {passed}/{total} passed")
    print(f"Config: T1 countries={len(t1)}, s_min={th.s_min_spend}, a_min={th.a_min_spend}")

    if write_report:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(_render_report(rows, passed, total), encoding="utf-8")
        print(f"Report: {write_report}")

    return 0 if passed == total else 1


def _render_report(rows: list[dict], passed: int, total: int) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# J-01 分级冒烟报告",
        "",
        f"**生成时间：** {ts}  ",
        f"**结果：** {passed}/{total} fixture 通过  ",
        f"**脚本：** `scripts/j01_level_smoke.py`  ",
        f"**夹具：** `fixtures/j01_level_smoke.json`  ",
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
        "| ID | 场景 | 结果 | level | chat_route | reason |",
        "|----|------|------|-------|------------|--------|",
    ]
    for r in rows:
        g = r["got"]
        mark = "PASS" if r["pass"] else "**FAIL**"
        lines.append(
            f"| {r['id']} | {r['title']} | {mark} | {g['level']} | {g['chat_route']} | {g['reason']} |"
        )
    lines.extend(["", "## 结论", ""])
    if passed == total:
        lines.append("**10/10 通过** — 可进入 C-06 关口验收与 AI 主链路并行准备。")
    else:
        lines.append("**未通过** — 修复 level_engine 或夹具期望后重跑。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="J-01 level_engine smoke")
    parser.add_argument(
        "--report",
        default=str(DEFAULT_REPORT),
        help="Markdown report path (default: docs/reports/J01_LEVEL_SMOKE_REPORT.md)",
    )
    parser.add_argument("--no-report", action="store_true", help="Skip writing report file")
    args = parser.parse_args()
    report_path = None if args.no_report else Path(args.report)
    raise SystemExit(run_smoke(write_report=report_path))


if __name__ == "__main__":
    main()
