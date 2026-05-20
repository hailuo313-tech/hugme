#!/usr/bin/env sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
python3 "${ROOT}/scripts/j03_dashboard_smoke.py"
python3 -m pytest "${ROOT}/tests/test_j03_dashboard_smoke.py" -q
