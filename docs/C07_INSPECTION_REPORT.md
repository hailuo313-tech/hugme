# C-07 检验报告：话术匹配覆盖率 + Prompt/安全红线

**任务：** C-07 — 审查话术全链路匹配覆盖率 + Prompt/安全红线  
**结论：** **通过（8/8 钩子有用例；红线 100% 拦截）**  
**依赖：** P3-12（safety_filter）、P3-20（script_match 编排）— 本评审覆盖现有实现 + 契约 stub

---

## 1. 话术全链路（8 钩子）

| Hook | 用例 ID | 契约测试 |
|------|---------|----------|
| inbound | C07-H-01 | ✅ |
| consumption | C07-H-02 | ✅ |
| probe | C07-H-03 | ✅ |
| grading | C07-H-04 | ✅ |
| reply | C07-H-05 | ✅ |
| operator | C07-H-06 | ✅ |
| outbound | C07-H-07 | ✅ |
| archive | C07-H-08 | ✅ |

P3-20 向量检索尚未接入；`evaluate_script_hook` 返回结构化 `degradation=p3_20_retrieval_not_wired`，不阻塞 C-07 契约验收。

详见 [`SCRIPT_MATCH_HOOKS.md`](SCRIPT_MATCH_HOOKS.md)、[`fixtures/c07_script_hooks.json`](../fixtures/c07_script_hooks.json)。

---

## 2. Prompt 红线（L1 / L9 / L10）

| 层 | 职责 | 验证 |
|----|------|------|
| L1_SAFETY | 未成年/自伤/违法/越狱 | `test_prompt_builder.py`、`RL-08` |
| L9_FORMAT | 输出格式约束 | 现有单测 |
| L10_ANCHOR | 末层强制规则 | 现有单测 |

`build_prompt(PromptInput())` 必含 `L1_SAFETY` 与「越狱」抵御说明。

---

## 3. 入站安全红线（100%）

| ID | 场景 | 层 |
|----|------|-----|
| RL-01 | CSAM | content_safety 关键词 |
| RL-02 | 越狱指令 | 关键词（C-07 补齐） |
| RL-03 | 暴力制造 | 关键词（C-07 补齐） |
| RL-04 | 自伤 moderation | 放行 → crisis |
| RL-05 | 危机检测 | crisis_intervention |
| RL-06 | 危机误报 | 否定过滤 |
| RL-07 | 未成年+成人 | minor_protection |
| RL-08 | L1 注入 | prompt_builder |

补充：`sexual/minors` moderation 拦截（`test_c07_safety_redlines`）。

---

## 4. 门禁

```powershell
.\scripts\check-c07-script-safety.ps1
```

报告：[`docs/reports/C07_SCRIPT_SAFETY_REPORT.md`](reports/C07_SCRIPT_SAFETY_REPORT.md)

---

## 5. 非阻塞遗留

- [ ] P3-20 接入向量 Top3 与 `conversation_script_hits`
- [ ] P3-12 与 `content_safety` 合并为统一 safety_filter 服务
- [ ] 出站/归档钩子 E2E（依赖 P1 入站队列）

---

## 6. 签署

| 检查项 | 结果 |
|--------|------|
| 8 钩子均有用例 | 通过 |
| 红线 100% 拦截 | 通过 |
| **阻塞项** | **无** |
