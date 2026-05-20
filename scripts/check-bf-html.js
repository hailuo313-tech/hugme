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

const tasks = eval(html.match(/const TASKS = (\[[\s\S]*?\]);/)[1]);
const parallel = eval("(" + html.match(/const PARALLEL = (\{[\s\S]*?\});/)[1] + ")");
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
