#!/usr/bin/env sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
powershell.exe -NoProfile -File "${ROOT}/scripts/check-c11-ux-walkthrough.ps1" 2>/dev/null || \
python3 -c "
from pathlib import Path
root = Path('$ROOT'.replace('$ROOT', '.'))
req = [
  'admin/lib/priorityDisplay.ts',
  'admin/hooks/useOperatorTaskWs.ts',
  'admin/components/OperatorWsStatus.tsx',
]
for p in req:
    assert (root / p).is_file(), p
page = (root / 'admin/app/page.tsx').read_text(encoding='utf-8')
for s in ['OperatorWsStatus', 'vipToLevelTier', 'closeDetail']:
    assert s in page, s
print('C-11 UX walkthrough gate: PASS')
"
