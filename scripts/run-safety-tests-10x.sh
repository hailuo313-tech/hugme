#!/usr/bin/env bash
set -euo pipefail

WORKDIR="${1:-/tmp/eris-safety-test}"
cd /opt/eris

TESTS=(
  tests/test_content_safety.py
  tests/test_minor_protection.py
  tests/test_reply_consistency.py
  tests/test_c07_safety_redlines.py
  tests/test_p3_11_12_14_ai_safety_delay.py
  tests/test_conversation_reply_consistency.py
  tests/test_open_api.py
  tests/test_notifications_send_now.py
  tests/test_persona_prompts.py
  tests/test_telegram_real_user_auto_reply.py
)

run_once() {
  docker compose run --rm --no-deps \
    -v "${WORKDIR}:/workspace" \
    api sh -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; cd /workspace && PYTHONPATH=app pytest ${TESTS[*]} -q --tb=line"
}

PASS=0
FAIL=0
for i in $(seq 1 10); do
  echo "========== RUN ${i} / 10 =========="
  if run_once; then
    PASS=$((PASS + 1))
    echo "RUN ${i}: PASS"
  else
    FAIL=$((FAIL + 1))
    echo "RUN ${i}: FAIL"
  fi
done

echo "========== SUMMARY =========="
echo "PASS=${PASS} FAIL=${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
  exit 1
fi
