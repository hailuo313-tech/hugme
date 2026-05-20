# C-12 E2E/压测脚本与 CI Nightly 审查

**任务：** C-12 — 审查 E2E/压测脚本与 CI nightly 配置  
**验收：** 流水线稳定 **3 天**（`nightly-e2e-ci` 连续 3 次绿）  
**依赖：** P5-T01（路线图；与 P5-01 MTProto E2E 并行演进）

---

## 1. 脚本清单

| 脚本 | 用途 | CI |
|------|------|-----|
| [`scripts/e2e/run.sh`](../scripts/e2e/run.sh) | D7-3 全量：注册→引导→**50** 轮聊天→handoff→Stripe | 本地/staging |
| [`scripts/e2e/smoke.sh`](../scripts/e2e/smoke.sh) | C-12 冒烟：**3** 轮聊天、跳过 Stripe | **nightly `e2e-smoke`** |
| [`scripts/perf/d8_2_retrieval_load.py`](../scripts/perf/d8_2_retrieval_load.py) | 记忆检索 P95 探针 | **不在 CI**（需 JWT + 真实用户） |

### 环境变量（`run.sh` / `smoke.sh`）

| 变量 | 默认 | smoke 配置 |
|------|------|------------|
| `API_BASE` | `http://127.0.0.1:8000` | 同左 |
| `E2E_CHAT_ROUNDS` | `50` | `3` |
| `E2E_SKIP_STRIPE` | `0` | `1` |
| `LLM_ECHO_FALLBACK` | — | nightly API 容器设为 `1` |

---

## 2. CI 工作流

| 工作流 | 触发 | Jobs |
|--------|------|------|
| [`pr-required-gates.yml`](../.github/workflows/pr-required-gates.yml) | PR → `main` | `admin-ci`, `backend-ci`, `ops-guard` |
| [`nightly-e2e-ci.yml`](../.github/workflows/nightly-e2e-ci.yml) | 每日 **06:00 UTC** + `workflow_dispatch` | `c12-audit`, `e2e-smoke` |

`e2e-smoke`：`docker compose up` → `bash scripts/e2e/smoke.sh`。

---

## 3. 三天稳定怎么记

1. 合并本任务后，在 GitHub **Actions → Nightly E2E CI** 查看每日运行。  
2. 每次 **绿**，往 [`fixtures/c12_nightly_stability.json`](../fixtures/c12_nightly_stability.json) 的 `runs` 追加：

```json
{"date":"2026-05-21","run_id":123456789,"conclusion":"success","jobs":["c12-audit","e2e-smoke"]}
```

3. `runs` 内连续 **3** 条 `success` → C-12 验收关闭。

---

## 4. 门禁

```powershell
.\scripts\check-c12-e2e-ci.ps1
```

```bash
bash scripts/check-c12-e2e-ci.sh
```

---

## 5. 与 P5-01 边界

| 项 | C-12（Cursor 审查） | P5-01（Devin E2E） |
|----|---------------------|-------------------|
| MTProto 入站 | 不在本任务 | 完整链路 |
| Telegram webhook E2E | nightly smoke | 扩展覆盖 |
| 1000 并发压测 | 仅审查 perf 脚本范围 | P5-02 |

---

## 6. 本地冒烟

```bash
docker compose up -d postgres redis api
LLM_ECHO_FALLBACK=1 API_BASE=http://127.0.0.1:8000 bash scripts/e2e/smoke.sh
```
