"""P1-09 evidence helper: verify at least one real Telegram account is online.

The script accepts a JSON file exported from staging/production monitoring:

[
  {"account_id": "...", "is_bot": false, "is_active": true,
   "status": "connected", "is_connected": true}
]

It exits non-zero when the evidence does not contain at least one active,
non-bot, connected account. Sensitive values such as phone/session strings are
not required and should not be included in the evidence file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ONLINE_STATUSES = {"connected", "online"}


def has_online_real_account(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get("is_bot") is True:
            continue
        if row.get("is_active") is False:
            continue
        if row.get("is_connected") is True:
            return True
        status = str(row.get("status") or "").lower()
        if status in ONLINE_STATUSES:
            return True
    return False


def load_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("accounts", [])
    if not isinstance(data, list):
        raise ValueError("evidence JSON must be a list or {'accounts': [...]}")
    return [row for row in data if isinstance(row, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_json", type=Path)
    args = parser.parse_args()

    rows = load_rows(args.evidence_json)
    if not has_online_real_account(rows):
        print("P1-09 FAIL: no active non-bot online account found")
        return 1
    print("P1-09 PASS: at least one active non-bot account is online")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
