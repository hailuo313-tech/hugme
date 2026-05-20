#!/usr/bin/env sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
python3 "${ROOT}/scripts/c09_ws_protocol_audit.py"
python3 -m pytest "${ROOT}/tests/test_c09_ws_protocol.py" "${ROOT}/tests/test_realtime.py" -q
