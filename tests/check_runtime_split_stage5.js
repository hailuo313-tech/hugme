const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const routes = read("app/core/api_next_routes.py");
const nginx = read("ops/nginx/api-next-sidecar.conf");
const compose = read("docker-compose.yml");
const health = read("app/api/health.py");
const main = read("app/main.py");

assert(routes.includes('return "ordinary"'), "classifier has ordinary");
assert(routes.includes('return "telegram_control"'), "classifier has telegram_control");
assert(routes.includes('return "video"'), "classifier has video");
assert(routes.includes("/api/v1/users"), "users are ordinary examples");
assert(routes.includes("/api/v1/telegram/"), "telegram control prefix");
assert(routes.includes("/api/v1/call-broadcast/"), "video prefix");

assert(compose.includes("PROCESS_ROLE: ${PROCESS_ROLE:-all}"), "legacy api stays all");
assert(compose.includes('profiles: ["api-next"]'), "api-next is profile gated");
assert(compose.includes("PROCESS_ROLE: api"), "api-next uses api role");
assert(compose.includes("127.0.0.1:8002:8000"), "api-next binds localhost 8002");
assert(compose.includes("EMBEDDING_WORKER_ENABLED: \"0\""), "api-next does not double-start embedding");
assert(compose.includes("HUMAN_TAKEOVER_RELEASE_WORKER_ENABLED: \"0\""), "api-next does not double-start takeover worker");

assert(nginx.includes("eris_api_legacy") && nginx.includes("127.0.0.1:8000"), "telegram stays on 8000");
assert(nginx.includes("eris_api_next") && nginx.includes("127.0.0.1:8002"), "ordinary can move to 8002");
assert(nginx.includes("location ^~ /api/v1/telegram/"), "telegram location pinned to legacy");
assert(nginx.includes("location ^~ /api/v1/call-broadcast/"), "video location pinned to legacy");
assert(nginx.includes("Do not replace the live"), "snippet is not an automatic cutover");

assert(health.includes('"status": "ok"'), "health status contract");
assert(health.includes('"service": "ERIS API"'), "health service contract");
assert(main.includes("elif owns_telegram_runtime(role):"), "api role skips telegram connect");
assert(!main.includes("telegram_command_gateway"), "stage 5 does not import gateway");

function classify(pathName) {
  const video = ["/api/v1/call-broadcast/", "/api/v1/video-reinvite/"];
  const telegram = ["/api/v1/telegram/", "/api/v1/mtproto", "/api/v1/telegram-user-migration/"];
  for (const prefix of video) {
    if (pathName.startsWith(prefix)) return "video";
  }
  for (const prefix of telegram) {
    if (pathName.startsWith(prefix)) return "telegram_control";
  }
  return "ordinary";
}

assert(classify("/api/v1/users") === "ordinary", "users are ordinary");
assert(classify("/api/v1/admin/users") === "ordinary", "admin users are ordinary");
assert(classify("/health") === "ordinary", "health is ordinary");
assert(classify("/api/v1/telegram/accounts/x/connect") === "telegram_control", "connect stays legacy");
assert(classify("/api/v1/call-broadcast/jobs") === "video", "video stays legacy");
assert(classify("/api/v1/video-reinvite/x") === "video", "video reinvite stays legacy");

console.log("stage5 checks passed");
