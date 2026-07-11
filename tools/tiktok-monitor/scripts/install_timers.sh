#!/usr/bin/env bash
set -euo pipefail
ROOT="/opt/eris-TIKTOK"
for f in \
  tiktok-account-audit.service tiktok-account-audit.timer \
  tiktok-live-probe.service tiktok-live-probe.timer; do
  install -m 644 "$ROOT/scripts/$f" "/etc/systemd/system/$f"
done
systemctl daemon-reload
# Automatic live detection runs every 20 minutes (local playback only, no paid API).
systemctl enable --now tiktok-live-probe.timer
# Viewer sampling stays manual/off to avoid extra load.
systemctl disable --now tiktok-live-sample.timer 2>/dev/null || true
systemctl stop tiktok-live-sample.service 2>/dev/null || true
systemctl enable --now tiktok-account-audit.timer
systemctl restart tiktok-monitor.service
echo "Timers (直播检测：自动每 20 分钟 + 人工按钮即时):"
systemctl list-timers 'tiktok-*' --no-pager
