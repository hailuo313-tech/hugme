const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const htmlPath = path.join(root, "docs/product/business-flow.html");
const rulesPath = path.join(root, "docs/product/_rules_data.json");
const rules = JSON.parse(fs.readFileSync(rulesPath, "utf8"));
const activeCount = rules.filter((r) => r.active).length;

let html = fs.readFileSync(htmlPath, "utf8");
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
