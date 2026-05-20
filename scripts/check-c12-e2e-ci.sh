#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/app"
PY="${PYTHON_BIN:-python3}"
"$PY" scripts/c12_e2e_ci_audit.py
"$PY" -m pytest tests/test_c12_e2e_ci_smoke.py -q
