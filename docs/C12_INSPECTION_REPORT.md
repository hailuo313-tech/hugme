# C-12 检验报告：E2E/CI Nightly 审查

**任务：** C-12 — 审查 E2E/压测脚本与 CI nightly 配置  
**结论：** **通过（审查交付 + nightly 工作流；连续 3 次绿已记账）**

---

## 1. 执行摘要

| 项 | 结果 |
|----|------|
| E2E 全量脚本 | `scripts/e2e/run.sh`（可调 `E2E_CHAT_ROUNDS`） |
| E2E CI 冒烟 | `scripts/e2e/smoke.sh`（3 轮 + 跳过 Stripe） |
| 压测脚本 | `scripts/perf/d8_2_retrieval_load.py`（明确 outside CI） |
| PR 门禁 | `pr-required-gates.yml`（3 jobs） |
| Nightly | `nightly-e2e-ci.yml`（`c12-audit` + `e2e-smoke`） |
| 稳定 3 天 | `fixtures/c12_nightly_stability.json` 记账 |

---

## 2. 交付物

| 文件 | 用途 |
|------|------|
| `app/services/e2e_ci_integration.py` | 契约常量 |
| `scripts/c12_e2e_ci_audit.py` | 审查脚本 |
| `.github/workflows/nightly-e2e-ci.yml` | 定时 nightly |
| `docs/C12_E2E_CI_REVIEW.md` | 审查说明 |
| `fixtures/c12_e2e_ci_checklist.json` | 8 项清单 |

---

## 3. 门禁

```powershell
.\scripts\check-c12-e2e-ci.ps1
```

---

## 4. 签署

| 检查项 | 结果 |
|--------|------|
| 脚本审查归档 | 通过 |
| Nightly 配置 | 通过 |
| 3 日稳定 | **3/3**（runs 26159926313, 26160200408, 26160289620） |
