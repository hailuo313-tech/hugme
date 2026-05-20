#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] && set -a && source .env && set +a || true
export PYTHONPATH="${ROOT}/app"
python -c "from services.mtproto.security_policy import check_production_session_policy; import sys; i=check_production_session_policy(); sys.exit(1 if i else 0)"
python -m pytest "${ROOT}/tests/test_mtproto_security_c15.py" -q
