#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
pip install -q jsonschema pytest
python -m pytest "${ROOT}/tests/test_schema_spec_c04.py" -q
