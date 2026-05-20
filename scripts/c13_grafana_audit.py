#!/usr/bin/env python3
"""C-13: audit Grafana dashboard and Prometheus alert rules."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from services.grafana_integration import (  # noqa: E402
    CORE_METRIC_ALERTS,
    DASHBOARD_REQUIRED_PANELS,
    MONITORING_FILES,
    REQUIRED_ALERTS,
    integration_contract,
)

REPORT = ROOT / "docs" / "reports" / "C13_GRAFANA_AUDIT_REPORT.md"
ALERTS_FILE = ROOT / "monitoring" / "alerts" / "eris-alerts.yml"
DASHBOARD_FILE = ROOT / "monitoring" / "grafana-dashboard-eris-mvp.json"


def _alert_names() -> set[str]:
    text = ALERTS_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^\s+- alert:\s+(\w+)", text, re.MULTILINE))


def _dashboard_titles() -> set[str]:
    data = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    return {p.get("title", "") for p in data.get("panels", []) if p.get("title")}


def main() -> int:
    failures: list[str] = []

    for rel in MONITORING_FILES:
        if not (ROOT / rel).is_file():
            failures.append(f"missing file: {rel}")

    found = _alert_names()
    for name in REQUIRED_ALERTS:
        if name not in found:
            failures.append(f"missing alert: {name}")

    for metric, alerts in CORE_METRIC_ALERTS.items():
        if not all(a in found for a in alerts):
            failures.append(f"core metric {metric} missing alert mapping")

    titles = _dashboard_titles()
    for panel in DASHBOARD_REQUIRED_PANELS:
        if panel not in titles:
            failures.append(f"dashboard missing panel: {panel}")

    prom = (ROOT / "monitoring/prometheus.yml").read_text(encoding="utf-8")
    if "eris-api:8000" not in prom or "/etc/prometheus/alerts" not in prom:
        failures.append("prometheus.yml scrape or rule_files incomplete")

    am = (ROOT / "monitoring/alertmanager/alertmanager.yml").read_text(encoding="utf-8")
    if "severity=\"critical\"" not in am or "discord" not in am:
        failures.append("alertmanager.yml routing incomplete")

    secrets_hit = []
    for path in MONITORING_FILES:
        text = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
        if "DISCORD_WEBHOOK_URL=https" in text or "password:" in text.lower():
            secrets_hit.append(path)
    if secrets_hit:
        failures.append(f"possible secrets in repo files: {secrets_hit}")

    contract = integration_contract()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-13 Grafana/alert audit (machine)",
        "",
        f"- alerts found: **{len(found)}**",
        f"- required alerts: **{len(REQUIRED_ALERTS)}**",
        f"- dashboard panels: **{len(titles)}**",
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
    lines.append("**PASS** — core metrics have alerts; dashboard panels present.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[PASS] C-13 Grafana/alert audit")
    print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
