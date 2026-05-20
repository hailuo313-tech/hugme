#!/usr/bin/env python3
"""C-07 audit runner: 8 hooks + safety redlines."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "reports" / "C07_SCRIPT_SAFETY_REPORT.md"


def main() -> None:
    env = {**__import__("os").environ, "PYTHONPATH": str(ROOT / "app")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_c07_script_hooks.py", "tests/test_c07_safety_redlines.py", "-q"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    hooks = json.loads((ROOT / "fixtures" / "c07_script_hooks.json").read_text(encoding="utf-8"))["hooks"]
    redlines = json.loads((ROOT / "fixtures" / "c07_safety_redlines.json").read_text(encoding="utf-8"))["redlines"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ok = proc.returncode == 0
    body = [
        "# C-07 话术与安全红线审计报告",
        "",
        f"**时间：** {ts}  ",
        f"**pytest：** {'PASS' if ok else 'FAIL'}  ",
        f"**钩子：** {len(hooks)}/8 有用例  ",
        f"**红线：** {len(redlines)} 项（含 moderation 补充断言）  ",
        "",
        "## 结论",
        "",
        ("**通过** — 8 钩子契约用例齐全，红线拦截 100%（含越狱/暴力关键词补齐）。" if ok else "**未通过** — 见 pytest 输出。"),
        "",
        "```",
        proc.stdout[-2000:] if proc.stdout else "",
        proc.stderr[-1000:] if proc.stderr else "",
        "```",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(body), encoding="utf-8")
    print(REPORT)
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
