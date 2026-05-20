# C-08 检验报告：J-02 AI 全链路冒烟

**任务：** C-08 — 执行 J-02 AI 全链路冒烟并记录耗时  
**结论：** **通过（8/8 fixture；端到端 <8s）**  
**关联：** C-07 话术/红线、D3-2 Prompt、`llm_orchestrator`、P3-20 script_match stub

---

## 1. 执行摘要

| 项 | 结果 |
|----|------|
| J-02 脚本 | `scripts/j02_ai_smoke.py` |
| 夹具数量 | **8** |
| 延迟预算 | **8000 ms**（含 `simulated_llm_delay_ms`） |
| 通过数 | **8** |
| 详细报告 | [`docs/reports/J02_AI_SMOKE_REPORT.md`](reports/J02_AI_SMOKE_REPORT.md) |

---

## 2. 冒烟链路（进程内）

```
入站安全(keyword) → 危机检测 → 分级(level_engine) → 8×话术钩子 → 10层Prompt → stub LLM
```

| 阶段 | 模块 | 说明 |
|------|------|------|
| safety | `content_safety._keyword_hit` | 命中即 `blocked` |
| crisis_detect | `crisis_intervention.detect_crisis_in_text` | 命中即 `crisis` 短路 |
| grading | `level_engine.calc_user_level` | 与 J-01 同配置 |
| script_hooks | `script_match_hooks.evaluate_script_hook` ×8 | P3-20 stub |
| prompt | `prompt_builder.build_prompt` | 10 层标签 |
| llm_stub | 可配置 `simulated_llm_delay_ms` | 不调用真实 OpenRouter |

**不在本次冒烟：** Redis 历史、DB 画像刷新、记忆检索 HTTP、真实 LLM API、Telegram 出站。

---

## 3. Fixture 覆盖矩阵

| ID | 业务场景 | outcome |
|----|----------|---------|
| J02-01 | 正常对话 | reply |
| J02-02 | CSAM 关键词 | blocked |
| J02-03 | 自伤危机 | crisis |
| J02-04 | S 级 + 角色/画像 Prompt | reply |
| J02-05 | D 级探测 | reply |
| J02-06 | 越狱拦截 | blocked |
| J02-07 | 带 history 上下文 | reply |
| J02-08 | 模拟 LLM 2s 延迟预算 | reply |

---

## 4. 门禁命令

```powershell
.\scripts\check-j02-ai-smoke.ps1
```

等价于：J-02 脚本 + `tests/test_j02_ai_smoke.py`。

---

## 5. 与路线图关系

| 任务 | 状态 |
|------|------|
| C-07 话术/红线 | baseline ✅ |
| C-08 J-02 AI 冒烟 | **本报告** |
| C-09 ws_protocol | 待 W7 |
| P5-01 MTProto→AI→投递 E2E | 待 C-08 后 |

---

## 6. 非阻塞遗留

- [ ] 服务器上 `generate_reply` + 真实 LLM 的 staging smoke（RUNBOOK D3-2）
- [ ] P3-20 向量话术命中后补钩子 E2E
- [ ] `orchestrator.dispatch` → `orchestrator.reply` 分布式 trace 耗时对齐

---

## 7. 签署

| 检查项 | 结果 |
|--------|------|
| 8 fixture 通过 | 通过 |
| 端到端 <8s（含模拟延迟） | 通过 |
| 耗时记录归档 | 通过 |
