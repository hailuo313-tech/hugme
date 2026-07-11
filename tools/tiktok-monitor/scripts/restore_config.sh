#!/bin/bash
set -euo pipefail
BACKUP="/opt/eris-TIKTOK/archive/pre-live-cleanup-20260705/config.json"
TARGET="/opt/eris-TIKTOK/config.json"
cp -a "$TARGET" "/opt/eris-TIKTOK/config.json.bak-before-restore-$(date +%Y%m%d%H%M%S)"
cp -a "$BACKUP" "$TARGET"
cd /opt/eris-TIKTOK
.venv/bin/python -c "
from pathlib import Path
from live_db import init_db, sync_accounts
from accounts_store import list_accounts
p = Path('data/tiktok_live.sqlite')
init_db(p)
sync_accounts(p, list_accounts(Path('config.json')))
print('restored accounts:', len(list_accounts(Path('config.json'))))
"
