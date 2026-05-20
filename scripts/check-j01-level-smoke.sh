#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
python "${ROOT}/scripts/j01_level_smoke.py"
python -m pytest "${ROOT}/tests/test_j01_level_smoke.py" -q
