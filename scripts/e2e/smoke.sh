#!/usr/bin/env bash
# C-12: CI-friendly E2E profile — 3 chat rounds, no Stripe (see docs/C12_E2E_CI_REVIEW.md).
set -euo pipefail
export E2E_CHAT_ROUNDS="${E2E_CHAT_ROUNDS:-3}"
export E2E_SKIP_STRIPE="${E2E_SKIP_STRIPE:-1}"
export E2E_SKIP_HANDOFF_REPLY="${E2E_SKIP_HANDOFF_REPLY:-1}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/run.sh" "$@"
