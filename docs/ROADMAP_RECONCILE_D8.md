# Roadmap Reconcile D8

This is a fact table for the live roadmap items D4-2 through D4-4 and D8-1,
D8-2, D8-4 versus the current `main` branch.

Scope:

- Source branch checked: repo tip (post-`main` merge + D4-2 task 9 branch); re-run this table after each `main` release.
- Live roadmap checked on 2026-05-14 from `https://hugme2.com/roadmap` (static `docs/eris-roadmap.html`; **站点可能滞后 git**，发布见 [RUNBOOK.md](../RUNBOOK.md)「公开路线图」)。
- This table does not mark roadmap cards done by inference. Each conclusion is
  based on merged code, merged docs, or an explicit PR number.

## Summary

| Roadmap item | Roadmap text | Main / PR evidence | Fact read | Recommendation |
| --- | --- | --- | --- | --- |
| D4-2 | Memory injection into Prompt by `memory_type` group + consistency check | D4-1 HTTP + hybrid retrieval: [app/services/memory_retriever.py](../app/services/memory_retriever.py). L6 渲染：[app/services/prompt_builder.py](../app/services/prompt_builder.py). **主链路注入**：[app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py) 在 `MEMORY_RETRIEVE_IN_PROMPT` 为真且 `db` 非空时调用 `memory_retriever.retrieve`，将命中写入 `PromptInput.memories`；开关见 [app/core/config.py](../app/core/config.py) `MEMORY_RETRIEVE_*`。**任务卡 9（规则一致性）**：[app/services/memory_consistency.py](../app/services/memory_consistency.py) 在注入前过滤与当前用户句互斥的记忆；`MEMORY_CONSISTENCY_*` 同 `config.py`；单测 [tests/test_memory_consistency.py](../tests/test_memory_consistency.py) + `tests/test_llm_orchestrator.py`。 | 与 `RUNBOOK.md` D4-2 段一致；默认不调 LLM（`MEMORY_CONSISTENCY_LLM_MAX_OUTPUT_TOKENS=0`）。若 `main` 尚未合并含 `memory_consistency.py` 的 PR，则一致性行仍以 PR 为准。 | 合并后可将路线图 D4-2 标为 done（可选后续：LLM 二次校验接 `MEMORY_CONSISTENCY_LLM_MAX_OUTPUT_TOKENS>0`）。 |
| D4-3 | `loneliness_score` four-dimension scorer + cold-start strategy | [scripts/init.sql](../scripts/init.sql) score columns；[app/services/loneliness_updater.py](../app/services/loneliness_updater.py) + 单测。[app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py) 在 `generate_reply` 中、在 D4-2 retrieve **之前**调用 `refresh_loneliness_score(..., user_text=...)`；[app/core/config.py](../app/core/config.py) 含 `LONELINESS_*` 与 `LONELINESS_REFRESH_ENABLED`。[app/services/prompt_builder.py](../app/services/prompt_builder.py) 渲染 L7。 | **loneliness 主链路已接线**；四维里 **initiation_score / trigger_threshold** 仍主要依赖 D4-4 worker 周期写回，不等同于「每轮四维全算」。 | D4-3 可标为 **大部分 done**；若产品要求「每轮四维分」再拆子任务。 |
| D4-4 | Score update Worker + `trigger_threshold` min-only calculation | [app/services/profile_score_worker.py](../app/services/profile_score_worker.py) + [app/services/profile_score_scheduler.py](../app/services/profile_score_scheduler.py) + `main` lifespan 启停；`pg_try_advisory_lock(6300413)`；配置 `SCORE_WORKER_*` / `TRIGGER_THRESHOLD_*`。默认 `SCORE_WORKER_ENABLED=false`，生产需显式打开。 | Worker **代码在库**；生产是否启用与 handoff/告警触发联动仍属运维/产品验收。 | 路线图 D4-4 可写 **partial**：模块 merged；启用与端到端证明待 release owner。 |
| D8-1 | Fix D7 beta bugs; issue list clear | Merged ops/baseline docs exist: [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) via PR [#31](https://github.com/hailuo313-tech/hugme/pull/31), [docs/PR_GATES_D8.md](PR_GATES_D8.md) via PR [#37](https://github.com/hailuo313-tech/hugme/pull/37) and PR [#39](https://github.com/hailuo313-tech/hugme/pull/39). Open D8 bug/preflight PRs still exist: PR [#33](https://github.com/hailuo313-tech/hugme/pull/33), PR [#35](https://github.com/hailuo313-tech/hugme/pull/35). | Governance/baseline docs are merged, but "issue list clear" is not proven while D8 bug/preflight PRs are still open. | Split remaining work as D8-1a merge/reject active bugfix PRs, D8-1b maintain issue checklist, D8-1c final smoke proof. Do not mark the broad D8-1 card done yet. |
| D8-2 | Performance tuning: slow-query indexes, worker concurrency; P95 < 2s | Memories index artifacts are merged in PR [#28](https://github.com/hailuo313-tech/hugme/pull/28): [scripts/migrations/d8-1_memories_btree_indexes.sql](../scripts/migrations/d8-1_memories_btree_indexes.sql), [scripts/migrations/d8-2_memories_embedding_ivfflat.sql](../scripts/migrations/d8-2_memories_embedding_ivfflat.sql), and [docs/D8_PERFORMANCE_INDEXES.md](D8_PERFORMANCE_INDEXES.md). Rollout/rollback proof is merged in PR [#36](https://github.com/hailuo313-tech/hugme/pull/36): [docs/D8_INDEX_ROLLOUT_CHECKLIST.md](D8_INDEX_ROLLOUT_CHECKLIST.md). [docs/D8_2_PERFORMANCE_PROOF.md](D8_2_PERFORMANCE_PROOF.md) archives a dated **fallback** retrieval smoke (`embedding_used=false`). [scripts/perf/d8_2_retrieval_load.py](../scripts/perf/d8_2_retrieval_load.py) is reproducible when `ERIS_OPERATOR_JWT` + `ERIS_USER_ID` are set. [app/core/config.py](../app/core/config.py) exposes `EMBEDDING_HTTP_TIMEOUT_SECONDS`, `EMBEDDING_SCHEDULER_MAX_INSTANCES`, `SCORE_WORKER_SCHEDULER_MAX_INSTANCES` (defaults preserve prior behavior). | **D8-2a**：migration SQL 在 `main`；生产是否已 `CONCURRENTLY` 执行须 release owner 用 D8_2 文档中的 SQL 自证。**D8-2b**：并发/超时可调，但 **vector 路径 P95 仍未举证**（生产缺 embedding backfill / `OPENAI_API_KEY` 时与历史快照一致）。**D8-2c**：仅证明 fallback 检索在极小数据量下 client P95 < 2s；**非**向量索引全路径。 | 不把整张 D8-2 标绿。路线图可写：「索引+migration 已合库；prod 执行 migration 待核对；worker 参数已暴露；fallback P95 有 smoke 记录；vector P95 待 embedding 与复跑压测」。 |
| D8-4 | Second beta + data dashboard: D1 retention / score distribution / token cost; seven-day first batch data | First-day metric pack is merged in PR [#34](https://github.com/hailuo313-tech/hugme/pull/34): [docs/BETA_DAY1_METRICS.md](BETA_DAY1_METRICS.md) and [scripts/beta/day1_metrics.sh](../scripts/beta/day1_metrics.sh). PR [#29](https://github.com/hailuo313-tech/hugme/pull/29) is merged and adds [docs/D8_4_BETA_DASHBOARD.md](D8_4_BETA_DASHBOARD.md), [docs/D8_ROUND2_METRICS_SPEC.md](D8_ROUND2_METRICS_SPEC.md), [scripts/beta/d8_4_report.sh](../scripts/beta/d8_4_report.sh), and the RUNBOOK D8-4 section. | Day-1 metrics and the D8-4 report package are on `main`. The roadmap still asks for second beta execution and seven-day data; token cost remains a lower-bound report until provider token usage is persisted. | Mark D8-4a Day-1 metrics and D8-4b report package done. Keep D8-4 partial until seven-day beta data and token-cost hardening/source proof are accepted. |

## PR Status Snapshot

Checked on 2026-05-14 with GitHub PR state:

- PR [#29](https://github.com/hailuo313-tech/hugme/pull/29) `chore(d8-4): add beta dashboard report`: merged into `main`.
- D8 repair/preflight PR [#33](https://github.com/hailuo313-tech/hugme/pull/33) `fix(admin): harden auth guard and fix basePath redirect bugs (D8-DEV-01)`: open.
- D8 repair/preflight PR [#35](https://github.com/hailuo313-tech/hugme/pull/35) `docs(d8-dev-02): add ADMIN_BETA_PREFLIGHT.md -- ops 5-minute UI checklist`: open.
- Other open PRs outside this reconcile decision set: #38, #32, #30, #24, #23, #21, #20, #16.

## RUNBOOK Text To Reconcile

Historical note (2026-05-14 snapshot): RUNBOOK 曾描述 D4-2/D4-3 早于代码合库。当前仓库中：

- D4-2：`llm_orchestrator` 在 `MEMORY_RETRIEVE_IN_PROMPT=true` 时调用 `memory_retrieve`，并可经 `memory_consistency` 过滤后再 `build_prompt`。
- D4-3：`generate_reply` 在 D4-2 之前调用 `refresh_loneliness_score`；`LONELINESS_REFRESH_ENABLED` 等为真实 `Settings` 字段。
- D4-4：`profile_score_worker` / scheduler 在库；默认 worker 关闭。

若 `CODEX_PARALLEL_BASELINE.md` 仍写旧 env 名，请以 `app/core/config.py` 与 `.env.example` 为准做一次全文核对。

## Cursor Handoff For CUR-D8-02

请按上表更新对外路线图；并注意：

1. D4-2 / D4-3 主链路在代码侧已对齐 RUNBOOK；D4-4 以 **worker 默认关 + 运维启用** 为 partial 叙述较诚实。
2. Mark only D8-2 memory-index subtasks done; keep worker concurrency and P95
   measurement as separate pending subtasks.
3. Treat PR #29 as merged; keep D8-4 partial until seven-day beta data and
   token-cost hardening/source proof are merged or explicitly removed from scope.
4. If the roadmap UI cannot represent subtasks, prefer "pending / partial" text
   over a green done state.
