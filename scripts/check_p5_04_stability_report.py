#!/usr/bin/env python3
"""Validate a P5-04 WebSocket stability report against the 72h acceptance bar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MIN_DURATION_HOURS = 72.0
MIN_UPTIME_PERCENT = 99.9
MAX_RECONNECTS = 5


def validate_report(payload: dict[str, Any]) -> list[str]:
    report = payload.get("report") or payload
    issues: list[str] = []

    duration = float(report.get("duration_hours") or 0)
    if duration < MIN_DURATION_HOURS:
        issues.append(f"duration_hours must be >= {MIN_DURATION_HOURS}; got {duration}")

    if report.get("zero_message_loss") is not True:
        issues.append("zero_message_loss must be true")

    ping_success_rate = float(report.get("ping_success_rate") or 0)
    if ping_success_rate < 100.0:
        issues.append(f"ping_success_rate must be 100.0; got {ping_success_rate}")

    uptime = float(report.get("uptime_percentage") or 0)
    if uptime < MIN_UPTIME_PERCENT:
        issues.append(f"uptime_percentage must be >= {MIN_UPTIME_PERCENT}; got {uptime}")

    reconnects = int(report.get("reconnect_count") or 0)
    if reconnects > MAX_RECONNECTS:
        issues.append(f"reconnect_count must be <= {MAX_RECONNECTS}; got {reconnects}")

    message_stats = report.get("message_stats") or {}
    lost = int(message_stats.get("lost_count") or 0)
    if lost != 0:
        issues.append(f"message_stats.lost_count must be 0; got {lost}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    issues = validate_report(payload)
    if issues:
        print(f"P5-04 report failed: {args.report}")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"P5-04 report passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
