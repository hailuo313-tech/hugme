#!/usr/bin/env python3
"""Ensure every account in config.json has a group field (default: own)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accounts_store import GROUP_OWN, normalize_group, save_config, load_config


def main() -> None:
    data = load_config(CONFIG)
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        print("no accounts")
        return
    changed = 0
    for item in accounts:
        if not isinstance(item, dict):
            continue
        before = item.get("group")
        item["group"] = normalize_group(str(before or ""))
        if before != item["group"]:
            changed += 1
    save_config(CONFIG, data)
    print(f"migrated {len(accounts)} accounts, updated {changed}")


if __name__ == "__main__":
    main()
