#!/usr/bin/env bash
# One-time server cleanup: archive old video-monitor artifacts, keep accounts in config.json
set -euo pipefail
ROOT="/opt/eris-TIKTOK"
ARCHIVE="$ROOT/archive/pre-live-cleanup-$(date +%Y%m%d)"
mkdir -p "$ARCHIVE/data" "$ARCHIVE/logs" "$ARCHIVE/code"

echo "==> Backup config.json"
cp -a "$ROOT/config.json" "$ARCHIVE/config.json"

echo "==> Archive old code/data/logs"
for f in monitor.py monitor.py.bak-* web_app.py.bak-*; do
  [ -f "$ROOT/$f" ] && mv "$ROOT/$f" "$ARCHIVE/code/" || true
done
for f in "$ROOT"/data/tiktok_metrics.sqlite "$ROOT"/data/*.csv "$ROOT"/data/batch_accounts.txt; do
  [ -e "$f" ] && mv "$f" "$ARCHIVE/data/" || true
done
for f in "$ROOT"/logs/*; do
  [ -e "$f" ] && mv "$f" "$ARCHIVE/logs/" || true
done
rm -rf "$ROOT/__pycache__"

echo "==> Slim config.json (accounts + live_monitor only)"
python3 - <<'PY'
import json
from pathlib import Path
root = Path("/opt/eris-TIKTOK")
cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
accounts = cfg.get("accounts") if isinstance(cfg.get("accounts"), list) else []
live_api = cfg.get("live_api") if isinstance(cfg.get("live_api"), dict) else {}
if not live_api and isinstance(cfg.get("tiktok_api"), dict):
    old = cfg["tiktok_api"]
    live_api = {
        "enabled": False,
        "provider": "apify",
        "endpoint": old.get("endpoint", ""),
        "api_key": old.get("api_key", ""),
        "timeout": old.get("timeout", 180),
    }
new_cfg = {
    "accounts": accounts,
    "live_monitor": cfg.get("live_monitor") or {
        "auto_probe_enabled": False,
        "auto_sample_enabled": False,
    },
    "live_api": live_api or {"enabled": False, "provider": "apify", "endpoint": "", "api_key": "", "timeout": 180},
}
(root / "config.json").write_text(json.dumps(new_cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"accounts kept: {len(accounts)}")
PY

echo "==> Done. Archive at $ARCHIVE"
