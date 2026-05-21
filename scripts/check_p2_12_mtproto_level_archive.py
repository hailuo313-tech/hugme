"""P2-12 evidence helper: validate MTProto real-user level archive.

The input is a sanitized JSON export from staging/production. It must contain at
least one telegram_real_user inbound event enriched by the level engine.

Accepted shapes:

[
  {
    "platform": "telegram_real_user",
    "external_user_id": "tg_...",
    "account_id": "acc_...",
    "message_type": "text",
    "metadata": {
      "user_level": "B",
      "chat_route": "ai_assisted",
      "level_reason": "t1_default_b",
      "country_tier": "T1"
    }
  }
]

or {"events": [...]}.

Do not include raw message content, phone numbers, session strings, or personal
data in the evidence file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LEVEL_ROUTES = {
    "S": "manual_premium",
    "A": "manual_premium",
    "B": "ai_assisted",
    "C": "ai_auto",
    "D": "ai_auto",
}


def load_events(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("events", [])
    if not isinstance(data, list):
        raise ValueError("archive JSON must be a list or {'events': [...]}")
    return [event for event in data if isinstance(event, dict)]


def validate_mtproto_level_archive(events: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    accepted = 0
    for index, event in enumerate(events):
        prefix = f"events[{index}]"
        if event.get("platform") != "telegram_real_user":
            continue
        metadata = event.get("metadata") or {}
        if not isinstance(metadata, dict):
            issues.append(f"{prefix}.metadata must be object")
            continue
        level = metadata.get("user_level")
        route = metadata.get("chat_route")
        if level not in LEVEL_ROUTES:
            issues.append(f"{prefix}.metadata.user_level invalid or missing")
            continue
        if route != LEVEL_ROUTES[level]:
            issues.append(f"{prefix}.metadata.chat_route does not match level")
            continue
        for key in ("external_user_id", "account_id", "message_type"):
            if not event.get(key):
                issues.append(f"{prefix}.{key} missing")
        for key in ("level_reason", "country_tier"):
            if not metadata.get(key):
                issues.append(f"{prefix}.metadata.{key} missing")
        if not any(issue.startswith(prefix) for issue in issues):
            accepted += 1
    if accepted < 1:
        issues.append("no valid telegram_real_user inbound level archive event found")
    return not issues, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_json", type=Path)
    args = parser.parse_args()

    ok, issues = validate_mtproto_level_archive(load_events(args.archive_json))
    if not ok:
        print("P2-12 FAIL:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("P2-12 PASS: MTProto real-user inbound level archive is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
