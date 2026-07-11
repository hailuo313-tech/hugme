#!/usr/bin/env bash
set -euo pipefail
ROOT="/opt/eris-TIKTOK"
for f in tiktok-account-audit.service tiktok-account-audit.timer; do
  install -m 644 "$ROOT/scripts/$f" "/etc/systemd/system/$f"
done
systemctl daemon-reload
systemctl disable --now tiktok-live-probe.timer tiktok-live-sample.timer 2>/dev/null || true
systemctl stop tiktok-live-probe.service tiktok-live-sample.service 2>/dev/null || true
systemctl enable --now tiktok-account-audit.timer
systemctl restart tiktok-monitor.service
echo "Timers (直播检测应只保留人工按钮，自动定时器必须为 disabled):"
systemctl list-timers 'tiktok-*' --no-pager
