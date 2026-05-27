#!/usr/bin/env bash
set -euo pipefail

ROOT="${ERIS_ROOT:-/opt/eris}"
CONTAINER="${ERIS_API_CONTAINER:-eris-api}"
TEST_TARGETS="${*:-tests/test_app_download_nurture.py tests/test_p3_13_message_schedule.py tests/test_p3_15_auto_delivery_worker.py tests/test_level_engine.py tests/test_llm_orchestrator.py tests/test_app_download_conversion.py}"

echo "Syncing tests into ${CONTAINER}..."
docker cp "${ROOT}/tests" "${CONTAINER}:/tmp/tests"
docker cp "${ROOT}/config" "${CONTAINER}:/tmp/config"
if [ -d "${ROOT}/db/migration" ]; then
  docker cp "${ROOT}/db" "${CONTAINER}:/tmp/db"
fi

echo "Installing pytest (if needed)..."
docker exec "${CONTAINER}" pip install -q pytest pytest-asyncio

echo "Running pytest..."
docker exec -e PYTHONPATH=/app "${CONTAINER}" \
  python -m pytest ${TEST_TARGETS} -q --tb=line
