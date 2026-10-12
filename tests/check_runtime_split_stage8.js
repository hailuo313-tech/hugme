const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const canary = read("app/services/runtime_canary.py");
const config = read("app/core/config.py");
const compose = read("docker-compose.yml");
const envExample = read(".env.example");
const main = read("app/main.py");

assert(canary.includes("1_internal"), "expand starts with 1 internal account");
assert(canary.includes("3_low_traffic"), "expand includes 3 low-traffic");
assert(canary.includes("10_accounts"), "expand includes 10 accounts");
assert(canary.includes("5_percent") && canary.includes("20_percent"), "expand includes percents");
assert(canary.includes("50_percent") && canary.includes("100_percent"), "expand includes 50/100");
assert(canary.includes("canary_disabled"), "disabled canary refuses switch");
assert(canary.includes("message_duplicate_or_lost"), "abort on lost/duplicate");
assert(canary.includes("AuthKeyDuplicated"), "abort on AuthKeyDuplicated");
assert(canary.includes("online_rate_drop"), "abort on online drop");
assert(canary.includes("video_failure_rate_up"), "abort on video failures");
assert(canary.includes("command_queue_backlog"), "abort on queue backlog");
assert(canary.includes("canary_enabled: bool = False"), "planner default is off");
assert(!canary.includes("UPDATE telegram_account_ownership"), "planner does not write ownership");
assert(!canary.includes("disconnect_account"), "planner does not disconnect legacy");

assert(config.includes("RUNTIME_CANARY_ENABLED: bool = False"), "config default false");
assert(envExample.includes("RUNTIME_CANARY_ENABLED=0"), "env example stays off");
assert(compose.includes("RUNTIME_CANARY_ENABLED: ${RUNTIME_CANARY_ENABLED:-false}"), "compose default false");
assert(!main.includes("runtime_canary"), "startup does not import canary");
assert(!main.includes("plan_account_switch"), "startup does not switch accounts");
assert(!fs.existsSync(path.join(root, "app/services/runtime_legacy_shutdown.py")) || !main.includes("runtime_legacy_shutdown"), "stage 8 does not start legacy shutdown");

console.log("stage8 checks passed");
