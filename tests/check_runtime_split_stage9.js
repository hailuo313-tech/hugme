const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const shutdown = read("app/services/runtime_legacy_shutdown.py");
const config = read("app/core/config.py");
const compose = read("docker-compose.yml");
const envExample = read(".env.example");
const main = read("app/main.py");

assert(shutdown.includes("MIN_STABLE_HOURS = 72"), "requires 72h stability");
assert(shutdown.includes("KEEP_IMAGE_DAYS = 7"), "keeps image 7 days");
assert(shutdown.includes("OBSERVE_AFTER_STOP_HOURS = 24"), "observes 24h after stop");
assert(shutdown.includes("legacy_flag_enabled"), "default flag blocks shutdown");
assert(shutdown.includes("legacy_clients_online"), "blocks when legacy clients exist");
assert(shutdown.includes("legacy_jobs_open"), "blocks when legacy jobs remain");
assert(shutdown.includes("runtime_not_stable_72h"), "blocks before 72h");
assert(shutdown.includes("not_all_accounts_on_runtime"), "blocks partial migration");
assert(shutdown.includes("legacy_enabled: bool = True"), "planner default keeps legacy");
assert(!shutdown.includes("disconnect_account"), "helper does not disconnect");
assert(!shutdown.includes("docker compose"), "helper does not stop containers");
assert(!shutdown.includes("PROCESS_ROLE"), "helper does not change process role");

assert(config.includes("LEGACY_TELEGRAM_RUNTIME_ENABLED: bool = True"), "config default true");
assert(envExample.includes("LEGACY_TELEGRAM_RUNTIME_ENABLED=1"), "env example keeps legacy on");
assert(
  compose.includes("LEGACY_TELEGRAM_RUNTIME_ENABLED: ${LEGACY_TELEGRAM_RUNTIME_ENABLED:-true}"),
  "compose default true",
);
assert(!main.includes("runtime_legacy_shutdown"), "startup does not import shutdown");
assert(!main.includes("legacy_shutdown_ready"), "startup does not close legacy");

assert(!main.includes("api-green"), "startup does not start api-green");
assert(!main.includes("bluegreen"), "startup does not start bluegreen");

console.log("stage9 checks passed");
