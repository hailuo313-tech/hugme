const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const gateway = read("app/services/telegram_command_gateway.py");
const ownership = read("app/services/runtime_ownership.py");
const admin = read("app/api/admin.py");
const accounts = read("app/api/telegram_accounts.py");
const review = read("app/services/call_broadcast/incoming_review.py");
const sessionManager = read("app/services/mtproto/session_manager.py");
const main = read("app/main.py");
const health = read("app/api/health.py");

assert(gateway.includes("queued_for_runtime"), "runtime path enqueues");
assert(gateway.includes('status="accepted"'), "queued result is accepted");
assert(gateway.includes("accepted_not_sent"), "queued result is not sent");
assert(gateway.includes('owner="legacy"'), "legacy owner is explicit");
assert(ownership.includes('owner="legacy"'), "missing ownership is legacy");
assert(ownership.includes("AsyncSessionLocal"), "ownership can open its own session");
assert(ownership.includes("except Exception:"), "ownership lookup failure falls back to legacy");

assert(admin.includes("submit_telegram_command"), "operator send goes through gateway");
assert(admin.includes('command_type="send_message"'), "operator send uses send_message");
assert(admin.includes("status_code=202"), "queued operator reply returns 202");
assert(admin.includes("accepted_not_sent"), "operator send does not show success when queued");

assert(accounts.includes('command_type="connect_account"'), "connect goes through gateway");
assert(accounts.includes('command_type="disconnect_account"'), "disconnect goes through gateway");
assert(accounts.includes('command_type="delete_account"'), "delete goes through gateway");
assert(accounts.includes('command_type="sync_profiles"'), "profile sync goes through gateway");

assert(review.includes("_gated_reject_inbound_call"), "reject goes through gateway");
assert(review.includes('command_type="answer_call"'), "accept goes through gateway");
assert(
  review.indexOf("ownership.is_runtime") < review.indexOf("await mark_job_streaming"),
  "runtime accept must not mark streaming first"
);

assert(sessionManager.includes("submit_telegram_command"), "reconnect goes through gateway");
assert(sessionManager.includes('command_type="connect_account"'), "reconnect uses connect_account");

assert(!main.includes("telegram_command_gateway"), "startup does not import gateway");
assert(health.includes('"status": "ok"') && health.includes('"service": "ERIS API"'), "health contract");
assert(!read("app/main.py").includes("start_canary"), "stage 6 does not start canary");

console.log("stage6 checks passed");
