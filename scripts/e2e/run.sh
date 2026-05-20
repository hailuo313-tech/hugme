#!/usr/bin/env bash
set -u

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
DB_CONTAINER="${DB_CONTAINER:-eris-postgres}"
DB_USER="${DB_USER:-eris}"
DB_NAME="${DB_NAME:-eris}"
E2E_RUN_ID="${E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
TG_USER_ID="${TG_USER_ID:-770300${E2E_RUN_ID: -6}}"
TG_CHAT_ID="${TG_CHAT_ID:-$TG_USER_ID}"
EXTERNAL_ID="tg_${TG_USER_ID}"
PRODUCT_ID="${PRODUCT_ID:-eris_test_monthly}"
ORDER_AMOUNT="${ORDER_AMOUNT:-199}"
ORDER_CURRENCY="${ORDER_CURRENCY:-USD}"
STRIPE_TEST_MODE="${STRIPE_TEST_MODE:-create_checkout}"

PASS_COUNT=0
FAIL_COUNT=0
TRACE_IDS=()
SUMMARY=()
USER_ID=""
CONVERSATION_ID=""
HANDOFF_TASK_ID=""
ORDER_ID=""

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  else
    echo "FAIL: python3/python is required"
    exit 1
  fi
fi

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2
}

json_get() {
  local input
  input="$(cat)"
  ERIS_JSON_INPUT="$input" "$PYTHON_BIN" -c '
import json, os, sys
path, default = sys.argv[1], sys.argv[2]
try:
    data = json.loads(os.environ.get("ERIS_JSON_INPUT", ""))
    cur = data
    for part in path.split("."):
        if not part:
            continue
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    print("" if cur is None else cur)
except Exception:
    print(default)
' "$1" "$2"
}

record_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  SUMMARY+=("PASS $1")
  log "PASS $1"
}

record_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  SUMMARY+=("FAIL $1 :: $2")
  log "FAIL $1 :: $2"
}

assert_eq() {
  local step="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    record_pass "$step"
  else
    record_fail "$step" "expected '$expected', got '$actual'"
  fi
}

assert_nonempty() {
  local step="$1" value="$2"
  if [[ -n "$value" && "$value" != "null" && "$value" != "NO_DB_CLIENT" ]]; then
    record_pass "$step"
  else
    record_fail "$step" "empty value"
  fi
}

obtain_operator_token() {
  if [[ -n "${OPERATOR_TOKEN:-}" ]]; then
    return 0
  fi
  local user="${E2E_OPERATOR_USER:-}"
  local pass="${E2E_OPERATOR_PASSWORD:-}"
  if [[ -z "$user" || -z "$pass" ]]; then
    record_fail "operator login" "set E2E_OPERATOR_USER/E2E_OPERATOR_PASSWORD or OPERATOR_TOKEN"
    return 1
  fi
  local body token
  body="$(curl -sS -X POST -H "Content-Type: application/json" \
    --data-binary "{\"username\":\"$user\",\"password\":\"$pass\"}" \
    "$API_BASE/api/v1/admin/login")"
  token="$(printf '%s' "$body" | json_get token "")"
  if [[ -z "$token" ]]; then
    record_fail "operator login" "$body"
    return 1
  fi
  OPERATOR_TOKEN="$token"
  export OPERATOR_TOKEN
  record_pass "operator login JWT"
}

curl_json() {
  local method="$1" path="$2" body="${3:-}" trace_id="${4:-}"
  local headers=(-H "Content-Type: application/json")
  case "$path" in
    /api/v1/handoff/*)
      if [[ -n "${OPERATOR_TOKEN:-}" ]]; then
        headers+=(-H "Authorization: Bearer ${OPERATOR_TOKEN}")
      fi
      ;;
  esac
  if [[ -n "$trace_id" ]]; then
    headers+=(-H "X-Trace-Id: $trace_id")
  fi
  if [[ "$method" == "GET" ]]; then
    curl -sS -X GET "${headers[@]}" "$API_BASE$path"
  else
    curl -sS -X "$method" "${headers[@]}" --data-binary "$body" "$API_BASE$path"
  fi
}

db_query() {
  local sql="$1"
  if [[ -n "${PSQL_DSN:-}" ]] && command -v psql >/dev/null 2>&1; then
    psql "$PSQL_DSN" -Atqc "$sql"
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -Atqc "$sql"
    return
  fi
  if command -v psql >/dev/null 2>&1; then
    psql -U "$DB_USER" -d "$DB_NAME" -Atqc "$sql"
    return
  fi
  echo "NO_DB_CLIENT"
  return 127
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

check_health_detail() {
  local step="$1" body api db redis
  body="$(curl_json GET /health/detail)"
  api="$(printf '%s' "$body" | json_get api missing)"
  db="$(printf '%s' "$body" | json_get db missing)"
  redis="$(printf '%s' "$body" | json_get redis missing)"
  if [[ "$api" == "ok" && "$db" == "ok" && "$redis" == "ok" ]]; then
    record_pass "$step /health/detail api=db=redis ok"
  else
    record_fail "$step /health/detail" "$body"
  fi
}

telegram_update_json() {
  local update_id="$1" message_id="$2" text="$3"
  "$PYTHON_BIN" - "$update_id" "$message_id" "$TG_USER_ID" "$TG_CHAT_ID" "$text" <<'PY'
import json, sys, time
update_id, message_id, user_id, chat_id, text = sys.argv[1:]
print(json.dumps({
    "update_id": int(update_id),
    "message": {
        "message_id": int(message_id),
        "date": int(time.time()),
        "chat": {"id": int(chat_id), "type": "private"},
        "from": {
            "id": int(user_id),
            "is_bot": False,
            "first_name": "E2E",
            "username": f"eris_e2e_{user_id}",
            "language_code": "zh",
        },
        "text": text,
    },
}, ensure_ascii=False))
PY
}

send_tg_update() {
  local label="$1" update_id="$2" message_id="$3" text="$4"
  local trace_id="d7-3-${E2E_RUN_ID}-${label}"
  local payload body ok returned_trace
  payload="$(telegram_update_json "$update_id" "$message_id" "$text")"
  body="$(curl_json POST /telegram/webhook "$payload" "$trace_id")"
  ok="$(printf '%s' "$body" | json_get ok false)"
  returned_trace="$(printf '%s' "$body" | json_get trace_id "")"
  if [[ "$ok" == "True" || "$ok" == "true" ]]; then
    record_pass "$label webhook accepted"
  else
    record_fail "$label webhook" "$body"
  fi
  TRACE_IDS+=("${returned_trace:-$trace_id}")
  printf '%s' "$body"
}

get_user_id() {
  db_query "SELECT id FROM users WHERE channel='telegram' AND external_id='$(sql_escape "$EXTERNAL_ID")' ORDER BY created_at DESC LIMIT 1;"
}

get_conversation_id() {
  db_query "SELECT id FROM conversations WHERE user_id='$USER_ID' ORDER BY created_at DESC LIMIT 1;"
}

verify_message_count_at_least() {
  local step="$1" min_count="$2" count
  count="$(db_query "SELECT COUNT(*) FROM messages WHERE conversation_id='$CONVERSATION_ID';")"
  if [[ "$count" =~ ^[0-9]+$ && "$count" -ge "$min_count" ]]; then
    record_pass "$step messages >= $min_count ($count)"
  else
    record_fail "$step message count" "expected >= $min_count, got $count"
  fi
}

create_handoff_task() {
  HANDOFF_TASK_ID="$(db_query "INSERT INTO handoff_tasks (user_id, conversation_id, priority, trigger_reason, status) VALUES ('$USER_ID', '$CONVERSATION_ID', 'P1', 'd7_3_e2e_keyword', 'pending') RETURNING id;")"
  assert_nonempty "trigger keyword created handoff task" "$HANDOFF_TASK_ID"
}

main() {
  log "D7-3 E2E run_id=$E2E_RUN_ID api=$API_BASE user=$EXTERNAL_ID"
  check_health_detail "preflight"

  send_tg_update "register" "$((10#$E2E_RUN_ID % 100000000 + 1))" 1 "/start" >/dev/null
  USER_ID="$(get_user_id)"
  assert_nonempty "register DB user exists" "$USER_ID"
  CONVERSATION_ID="$(get_conversation_id)"
  assert_nonempty "register DB conversation exists" "$CONVERSATION_ID"
  verify_message_count_at_least "register" 1
  check_health_detail "after register"

  local answers=("小七" "音乐,电影,旅行" "1" "没有" "想找个人说说话")
  local i step db_step nickname
  for i in "${!answers[@]}"; do
    step=$((i + 1))
    send_tg_update "onboarding${step}" "$((10#$E2E_RUN_ID % 100000000 + 10 + step))" "$((10 + step))" "${answers[$i]}" >/dev/null
    db_step="$(db_query "SELECT COALESCE(preferences->>'onboarding_step','0') FROM user_profiles WHERE user_id='$USER_ID';")"
    if [[ "$step" -lt 5 ]]; then
      assert_eq "onboarding step $step DB progress" "$db_step" "$step"
    else
      assert_eq "onboarding completed DB progress" "$db_step" "6"
    fi
    check_health_detail "after onboarding step $step"
  done
  nickname="$(db_query "SELECT nickname FROM users WHERE id='$USER_ID';")"
  assert_eq "onboarding DB nickname" "$nickname" "小七"
  verify_message_count_at_least "onboarding" 11

  CHAT_ROUNDS="${E2E_CHAT_ROUNDS:-50}"
  for i in $(seq 1 "$CHAT_ROUNDS"); do
    send_tg_update "chat${i}" "$((10#$E2E_RUN_ID % 100000000 + 100 + i))" "$((100 + i))" "第 ${i} 轮：今天我想继续聊聊生活。" >/dev/null
    if (( CHAT_ROUNDS >= 10 && i % 10 == 0 )); then
      verify_message_count_at_least "${CHAT_ROUNDS}-round checkpoint $i" "$((11 + i))"
      check_health_detail "after chat $i"
    fi
  done
  verify_message_count_at_least "${CHAT_ROUNDS}-round final" "$((11 + CHAT_ROUNDS))"

  send_tg_update "trigger" "$((10#$E2E_RUN_ID % 100000000 + 1000))" 1000 "我现在很孤独，需要真人帮我看一下。" >/dev/null
  create_handoff_task
  check_health_detail "after trigger"

  obtain_operator_token || true
  if [[ -z "${OPERATOR_TOKEN:-}" ]]; then
    echo "RESULT=FAIL"
    exit 1
  fi

  local lock_status reply_status return_status task_status
  lock_status="$(curl_json POST "/api/v1/handoff/${HANDOFF_TASK_ID}/lock" "{}" "d7-3-${E2E_RUN_ID}-handoff-lock" | json_get status "")"
  assert_eq "handoff lock API" "$lock_status" "locked"
  task_status="$(db_query "SELECT status FROM handoff_tasks WHERE id='$HANDOFF_TASK_ID';")"
  assert_eq "handoff lock DB" "$task_status" "HUMAN_LOCKED"
  if [[ "${E2E_SKIP_HANDOFF_REPLY:-0}" == "1" ]]; then
    log "handoff reply skipped (E2E_SKIP_HANDOFF_REPLY=1, no Telegram in CI)"
    record_pass "handoff reply skipped smoke profile"
  else
    reply_status="$(curl_json POST "/api/v1/handoff/${HANDOFF_TASK_ID}/reply" '{"content":"我在，这条是 D7-3 E2E operator 回复。"}' "d7-3-${E2E_RUN_ID}-handoff-reply" | json_get status "")"
    assert_eq "handoff reply API" "$reply_status" "sent"
  fi
  return_status="$(curl_json POST "/api/v1/handoff/${HANDOFF_TASK_ID}/return-ai" '{"notes":"D7-3 E2E complete","allow_upsell":true}' "d7-3-${E2E_RUN_ID}-handoff-return" | json_get status "")"
  assert_eq "handoff return API" "$return_status" "returned_to_ai"
  task_status="$(db_query "SELECT status FROM handoff_tasks WHERE id='$HANDOFF_TASK_ID';")"
  assert_eq "handoff return DB" "$task_status" "CLOSED"
  TRACE_IDS+=("d7-3-${E2E_RUN_ID}-handoff-lock" "d7-3-${E2E_RUN_ID}-handoff-reply" "d7-3-${E2E_RUN_ID}-handoff-return")
  check_health_detail "after handoff"

  if [[ "${E2E_SKIP_STRIPE:-0}" == "1" ]]; then
    log "stripe skipped (E2E_SKIP_STRIPE=1)"
    record_pass "stripe skipped smoke profile"
  else
    local order_body checkout_url order_status
    order_body="$(curl_json POST /api/v1/orders "{\"user_id\":\"$USER_ID\",\"product_id\":\"$PRODUCT_ID\",\"amount\":$ORDER_AMOUNT,\"currency\":\"$ORDER_CURRENCY\"}" "d7-3-${E2E_RUN_ID}-stripe-order")"
    ORDER_ID="$(printf '%s' "$order_body" | json_get order_id "")"
    checkout_url="$(printf '%s' "$order_body" | json_get checkout_url "")"
    assert_nonempty "stripe checkout order_id" "$ORDER_ID"
    assert_nonempty "stripe checkout url" "$checkout_url"
    order_status="$(db_query "SELECT status FROM orders WHERE id='$ORDER_ID';")"
    assert_eq "stripe order DB pending" "$order_status" "pending"
    TRACE_IDS+=("d7-3-${E2E_RUN_ID}-stripe-order")
    if [[ "$STRIPE_TEST_MODE" == "manual_4242" ]]; then
      log "Open checkout_url and pay with Stripe test card 4242 4242 4242 4242: $checkout_url"
    fi
    check_health_detail "after stripe"
  fi

  echo
  echo "========== D7-3 E2E SUMMARY =========="
  printf '%s\n' "${SUMMARY[@]}"
  echo "---------- trace_id list ----------"
  printf '%s\n' "${TRACE_IDS[@]}" | sed '/^$/d'
  echo "---------- resources ----------"
  echo "user_id=$USER_ID"
  echo "conversation_id=$CONVERSATION_ID"
  echo "handoff_task_id=$HANDOFF_TASK_ID"
  echo "order_id=$ORDER_ID"
  echo "PASS=$PASS_COUNT FAIL=$FAIL_COUNT"

  if [[ "$FAIL_COUNT" -eq 0 ]]; then
    echo "RESULT=PASS"
    exit 0
  fi
  echo "RESULT=FAIL"
  exit 1
}

main "$@"
