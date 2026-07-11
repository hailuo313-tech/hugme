#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from accounts_store import list_accounts
from live_db import init_db, sync_accounts

p = ROOT / "data" / "tiktok_live.sqlite"
cfg = ROOT / "config.json"
init_db(p)
sync_accounts(p, list_accounts(cfg))
print("synced", len(list_accounts(cfg)))
