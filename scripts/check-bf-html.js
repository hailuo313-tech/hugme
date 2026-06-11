const fs = require("fs");
const path = process.argv[2] || "/usr/share/nginx/html/business-flow.html";
let html = fs.readFileSync(path, "utf8");
const bom = html.charCodeAt(0) === 0xfeff;
if (bom) html = html.slice(1);
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) {
  console.error("no inline script");
  process.exit(1);
}
try {
  new (require("vm").Script)(m[1]);
} catch (e) {
  console.log(JSON.stringify({ path, bom, bytes: fs.statSync(path).size, syntax: "ERR", message: e.message }));
  process.exit(2);
}

const rulesMatch = html.match(/const RULES = (\[[\s\S]*?\]);/);
if (rulesMatch) {
  const rules = JSON.parse(rulesMatch[1]);
  const active = rules.filter((r) => r.active).length;
  const required = [
    "channel.mtproto_direct",
    "channel.bot_webhook",
    "conversion.asset_keyword",
    "deprecated.eight_hooks",
  ];
  const missing = required.filter((id) => !rules.some((r) => r.id === id));
  if (missing.length) {
    console.log(
      JSON.stringify({
        path,
        bom,
        bytes: fs.statSync(path).size,
        syntax: "OK",
        rules: "ERR",
        missing,
      })
    );
    process.exit(3);
  }
  console.log(
    JSON.stringify({
      path,
      bom,
      bytes: fs.statSync(path).size,
      syntax: "OK",
      rules: "OK",
      total: rules.length,
      active,
    })
  );
  process.exit(0);
}

const tasksMatch = html.match(/const TASKS = (\[[\s\S]*?\]);/);
const parallelMatch = html.match(/const PARALLEL = (\{[\s\S]*?\});/);
if (!tasksMatch || !parallelMatch) {
  console.log(
    JSON.stringify({
      path,
      bom,
      bytes: fs.statSync(path).size,
      syntax: "OK",
      rules: "ERR",
      message: "missing RULES or legacy TASKS block",
    })
  );
  process.exit(3);
}

const tasks = eval(tasksMatch[1]);
const parallel = eval("(" + parallelMatch[1] + ")");
const paraBlock = html.match(/const PARA_UI = \{([\s\S]*?)\};/);
const paraUiKeys = new Set(
  paraBlock ? [...paraBlock[1].matchAll(/^\s*(\w+):/gm)].map((x) => x[1]) : []
);
const bad = [];
for (const t of tasks) {
  const pt = (parallel[t.id] || { t: "wait" }).t;
  if (!paraUiKeys.has(pt)) bad.push(`${t.id}:${pt}`);
}
if (bad.length) {
  console.log(
    JSON.stringify({
      path,
      bom,
      bytes: fs.statSync(path).size,
      syntax: "OK",
      parallel: "ERR",
      bad,
    })
  );
  process.exit(3);
}
console.log(JSON.stringify({ path, bom, bytes: fs.statSync(path).size, syntax: "OK", parallel: "OK" }));
