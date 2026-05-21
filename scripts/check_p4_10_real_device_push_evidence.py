"""P4-10 evidence helper: validate real-device push proof.

The evidence file must be sanitized. Do not include full FCM/APNs tokens, phone
numbers, user names, or notification body text from real users.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VALID_PROVIDERS = {"fcm", "apns"}
VALID_ENVIRONMENTS = {"staging", "production"}


def load_attempts(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("attempts", [])
    if not isinstance(data, list):
        raise ValueError("evidence JSON must be a list or {'attempts': [...]}")
    return [row for row in data if isinstance(row, dict)]


def validate_real_device_push_evidence(attempts: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    successes = 0
    for index, attempt in enumerate(attempts):
        prefix = f"attempts[{index}]"
        provider = str(attempt.get("provider") or "").lower()
        environment = str(attempt.get("environment") or "").lower()
        token_hash = str(attempt.get("device_token_hash") or "")

        if provider not in VALID_PROVIDERS:
            issues.append(f"{prefix}.provider must be fcm or apns")
        if environment not in VALID_ENVIRONMENTS:
            issues.append(f"{prefix}.environment must be staging or production")
        if attempt.get("success") is not True:
            issues.append(f"{prefix}.success must be true")
        if not attempt.get("message_id"):
            issues.append(f"{prefix}.message_id missing")
        if len(token_hash) < 12:
            issues.append(f"{prefix}.device_token_hash missing or too short")
        if attempt.get("device_token"):
            issues.append(f"{prefix}.device_token must not contain raw token")
        if not attempt.get("received_at"):
            issues.append(f"{prefix}.received_at missing")

        if not any(issue.startswith(prefix) for issue in issues):
            successes += 1

    if successes < 1:
        issues.append("no valid real-device push success evidence found")
    return not issues, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_json", type=Path)
    args = parser.parse_args()

    ok, issues = validate_real_device_push_evidence(load_attempts(args.evidence_json))
    if not ok:
        print("P4-10 FAIL:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("P4-10 PASS: real-device push evidence is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
