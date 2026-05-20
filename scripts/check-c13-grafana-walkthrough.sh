#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/app"
PY="${PYTHON_BIN:-python3}"
"$PY" scripts/c13_grafana_audit.py
"$PY" -m pytest tests/test_c13_grafana_smoke.py -q
