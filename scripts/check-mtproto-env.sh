#!/usr/bin/env bash
# C-03: verify MTProto-related vars in .env (or exported env).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHONPATH=app python - <<'PY'
import sys

from core.mtproto_env import mtproto_env_status

ok, issues = mtproto_env_status()
if ok:
    print("MTProto env OK (C-03 checklist passed).")
    sys.exit(0)
print("MTProto env incomplete:")
for item in issues:
    print(f"  - {item}")
print("\nSee docs/MTProto_ENV_SETUP.md and .env.template")
sys.exit(1)
PY
