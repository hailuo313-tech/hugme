const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const ownership = read("app/services/runtime_ownership.py");
assert(ownership.includes("def legacy_worker_should_handle("), "legacy helper exists");
assert(ownership.includes("async def legacy_worker_should_handle_account("), "account helper exists");
assert(ownership.includes('owner="legacy"'), "missing row is legacy");
assert(ownership.includes("def switch_admission("), "switch admission exists");
assert(ownership.includes("pending_review"), "pending review is a separate probe");
assert(ownership.includes("next_generation"), "generation increments");

const files = {
  "app/services/message_schedule_service.py": "message_schedule_service.tick.skip_runtime_owned",
  "app/services/auto_delivery_worker.py": "auto_delivery_worker.tick.skip_runtime_owned",
  "app/services/fixed_auto_reply_service.py": "failure_reason = 'runtime_owned'",
  "app/services/telegram_user_migration.py": "telegram_user_migration.skip_runtime_owned",
  "app/services/video_reinvite.py": "video_reinvite.skip_runtime_owned",
  "app/services/call_broadcast/worker.py": "call_broadcast_worker.skip_runtime_owned",
  "app/services/telegram_account_health.py": "legacy_worker_should_handle_account",
  "app/services/mtproto/account_pool.py": "runtime_owned:",
};

for (const [rel, needle] of Object.entries(files)) {
  assert(read(rel).includes(needle), `${rel} has fencing`);
}

assert(read("app/services/message_schedule_service.py").includes("SET status = 'pending'"), "schedule releases claim");
assert(read("app/services/fixed_auto_reply_service.py").includes("SET status = 'pending'"), "auto reply releases claim");
assert(read("app/services/call_broadcast/worker.py").includes("requeue_job"), "outbound video requeues");
assert(read("app/services/telegram_user_migration.py").includes("status = 'pending'"), "migration releases claim");

assert(!fs.existsSync(path.join(root, "app/services/runtime_canary.py")) || !read("app/main.py").includes("runtime_canary"), "canary not started");
assert(!read("app/main.py").includes("start_canary"), "stage 7 does not start canary");

console.log("stage7 checks passed");
