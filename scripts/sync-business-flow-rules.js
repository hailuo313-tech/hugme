const fs = require("fs");
const path = require("path");

require("./build-business-flow-rules.js");

const root = path.join(__dirname, "..");
const htmlPath = path.join(root, "docs/product/business-flow.html");
const rules = JSON.parse(
  fs.readFileSync(path.join(root, "docs/product/_rules_data.json"), "utf8")
);

let html = fs.readFileSync(htmlPath, "utf8");
const activeCount = rules.filter((r) => r.active).length;

html = html.replace(
  /const RULES = \[[\s\S]*?\];/,
  `const RULES = ${JSON.stringify(rules, null, 2)};`
);

html = html.replace(
  /<footer>ERIS 智能陪伴系统 · 业务流程 \+ 规则条件 · 共 \d+ 条 · 生效 \d+ 条<\/footer>/,
  `<footer>ERIS 智能陪伴系统 · 业务流程 + 规则条件 · 共 ${rules.length} 条 · 生效 ${activeCount} 条</footer>`
);

fs.writeFileSync(htmlPath, html, "utf8");
console.log("synced", htmlPath, { total: rules.length, active: activeCount });
