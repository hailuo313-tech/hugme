#!/usr/bin/env python3
"""Validate a P5-02 load-test report against the 1000 concurrency SLA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MIN_CONCURRENCY = 1000
MAX_P99_MS = 500.0


def validate_report(report: dict[str, Any]) -> list[str]:
    summary = report.get("test_summary") or {}
    criteria = summary.get("acceptance_criteria") or {}
    latency = report.get("overall_latency_ms") or {}
    issues: list[str] = []

    concurrency = int(summary.get("concurrency") or 0)
    if concurrency < MIN_CONCURRENCY:
        issues.append(f"concurrency must be >= {MIN_CONCURRENCY}; got {concurrency}")

    threshold = float(criteria.get("p99_threshold_ms") or 0)
    if threshold > MAX_P99_MS or threshold <= 0:
        issues.append(f"p99 threshold must be <= {MAX_P99_MS}ms; got {threshold}")

    p99_actual = float(criteria.get("p99_actual_ms") or latency.get("p99") or 0)
    if p99_actual <= 0:
        issues.append("p99_actual_ms must be present and positive")
    elif p99_actual >= MAX_P99_MS:
        issues.append(f"p99 must be < {MAX_P99_MS}ms; got {p99_actual}")

    if criteria.get("passed") is not True:
        issues.append("acceptance_criteria.passed must be true")

    endpoints = report.get("endpoints") or {}
    if not endpoints:
        issues.append("report must include per-endpoint results")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    issues = validate_report(report)
    if issues:
        print(f"P5-02 report failed: {args.report}")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"P5-02 report passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
