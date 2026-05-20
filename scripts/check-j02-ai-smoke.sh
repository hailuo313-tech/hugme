#!/usr/bin/env bash
# C-08: J-02 AI pipeline smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
python3 "${ROOT}/scripts/j02_ai_smoke.py"
python3 -m pytest "${ROOT}/tests/test_j02_ai_smoke.py" -q
