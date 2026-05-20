#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/app"
pip install -q pytest pytest-cov
python -m pytest "${ROOT}/tests/test_level_engine.py" -q \
  --cov=services.level_engine \
  --cov-branch \
  --cov-fail-under=85 \
  --cov-report=term-missing:skip-covered
