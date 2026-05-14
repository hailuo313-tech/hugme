# Roadmap Reconcile D8

This is a fact table for the live roadmap items D4-2 through D4-4 and D8-1,
D8-2, D8-4 versus the current `main` branch.

Scope:

- Source branch checked: `main` at `eb93d6e`.
- Live roadmap checked on 2026-05-14 from `https://hugme2.com/roadmap`.
- This table does not mark roadmap cards done by inference. Each conclusion is
  based on merged code, merged docs, or an explicit PR number.

## Summary

| Roadmap item | Roadmap text | Main / PR evidence | Fact read | Recommendation |
| --- | --- | --- | --- | --- |
| D4-2 | Memory injection into Prompt by `memory_type` group + consistency check | [app/services/memory_retriever.py](../app/services/memory_retriever.py) and PR [#26](https://github.com/hailuo313-tech/hugme/pull/26) prove D4-1 retrieval exists. [app/services/prompt_builder.py](../app/services/prompt_builder.py) can render `L6_MEMORY`. But [app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py) still passes `memories=None` into `build_prompt`; [app/core/config.py](../app/core/config.py) has no `MEMORY_RETRIEVE_IN_PROMPT` field. | Retrieval exists, but automatic prompt injection and consistency check are not present on `main`. RUNBOOK currently describes the desired integration as if it exists. | 建议拆子任务: D4-2a retrieval already done (#26/#27), D4-2b orchestrator injects Top-K memories into `L6_MEMORY`, D4-2c consistency check. Also 建议删除/降级 RUNBOOK D4-2 "已接入"文案 until code lands. |
| D4-3 | `loneliness_score` four-dimension scorer + cold-start strategy | [scripts/init.sql](../scripts/init.sql) defines score columns (`initiation_score`, `emotion_score`, `retention_score`, `dependency_score`, `loneliness_score`, `trigger_threshold`). [app/services/prompt_builder.py](../app/services/prompt_builder.py) reads `profile.loneliness_score` and renders `L7_CONVERSATION_STATE`. [tests/test_prompt_builder.py](../tests/test_prompt_builder.py) covers the prompt band rendering. | Schema and prompt display exist, but no `loneliness_updater` / scorer service, worker, or tests were found on `main`. [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) already notes `LONELINESS_REFRESH_ENABLED` is RUNBOOK-only, not a real config field. | 建议拆子任务: D4-3a scorer service, D4-3b cold-start defaults and tests, D4-3c orchestrator/worker writeback. Do not mark done. 建议删除/降级 RUNBOOK claims that every turn refreshes `loneliness_score`. |
| D4-4 | Score update Worker + `trigger_threshold` min-only calculation | [scripts/init.sql](../scripts/init.sql) has `trigger_threshold` and score columns. [app/api/admin.py](../app/api/admin.py) reads `loneliness_score` for admin views. No score worker, threshold calculation service, scheduler, or tests were found under [app/services](../app/services), [app/api](../app/api), or [tests](../tests). | Data fields exist, but the worker and min-only threshold logic are not implemented on `main`. | 建议拆子任务: D4-4a scoring worker, D4-4b min-only threshold formula, D4-4c handoff/alert trigger integration, D4-4d tests. Do not mark done. |
| D8-1 | Fix D7 beta bugs; issue list clear | Merged ops/baseline docs exist: [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) via PR [#31](https://github.com/hailuo313-tech/hugme/pull/31), [docs/PR_GATES_D8.md](PR_GATES_D8.md) via PR [#37](https://github.com/hailuo313-tech/hugme/pull/37) and PR [#39](https://github.com/hailuo313-tech/hugme/pull/39). Open D8 bug/preflight PRs still exist: PR [#33](https://github.com/hailuo313-tech/hugme/pull/33), PR [#35](https://github.com/hailuo313-tech/hugme/pull/35). | Governance/baseline docs are merged, but "issue list clear" is not proven while D8 bug/preflight PRs are still open. | 建议拆子任务: D8-1a merge/reject active bugfix PRs, D8-1b maintain issue checklist, D8-1c final smoke proof. Do not mark the broad D8-1 card done yet. |
| D8-2 | Performance tuning: slow-query indexes, worker concurrency; P95 < 2s | Memories index artifacts are merged in PR [#28](https://github.com/hailuo313-tech/hugme/pull/28): [scripts/migrations/d8-1_memories_btree_indexes.sql](../scripts/migrations/d8-1_memories_btree_indexes.sql), [scripts/migrations/d8-2_memories_embedding_ivfflat.sql](../scripts/migrations/d8-2_memories_embedding_ivfflat.sql), and [docs/D8_PERFORMANCE_INDEXES.md](D8_PERFORMANCE_INDEXES.md). Rollout/rollback proof is merged in PR [#36](https://github.com/hailuo313-tech/hugme/pull/36): [docs/D8_INDEX_ROLLOUT_CHECKLIST.md](D8_INDEX_ROLLOUT_CHECKLIST.md). | Slow-query index work is present. Worker concurrency and measured P95 < 2s proof are not visible on `main`. D8-2 should not be treated as fully done unless the roadmap card is narrowed to "memory indexes". | 建议拆子任务: D8-2a memories indexes done (#28/#36), D8-2b worker concurrency, D8-2c P95 measurement. Mark only the index subtask done, not the full D8-2 card. |
| D8-4 | Second beta + data dashboard: D1 retention / score distribution / token cost; seven-day first batch data | First-day metric pack is merged in PR [#34](https://github.com/hailuo313-tech/hugme/pull/34): [docs/BETA_DAY1_METRICS.md](BETA_DAY1_METRICS.md) and [scripts/beta/day1_metrics.sh](../scripts/beta/day1_metrics.sh). Beta invite/runbook exists in [docs/BETA_CHECKLIST.md](BETA_CHECKLIST.md). A more specific D8-4 dashboard/report PR [#29](https://github.com/hailuo313-tech/hugme/pull/29) is still open and contains `docs/D8_4_BETA_DASHBOARD.md` plus `scripts/beta/d8_4_report.sh`, not merged to `main`. | Day-1 metrics are done. The roadmap asks for second beta, data dashboard, D1 retention, score distribution, token cost, and seven-day data; that is not fully on `main` yet. | 建议拆子任务: D8-4a Day-1 metrics done (#34), D8-4b merge/finish dashboard report (#29), D8-4c run seven-day beta data collection, D8-4d token-cost source. Do not mark full D8-4 done. |

## RUNBOOK Text To Reconcile

The following RUNBOOK claims read like implementation facts, but current `main`
does not contain the corresponding code path:

- [RUNBOOK.md](../RUNBOOK.md) says D4-2 calls `memory_retriever.retrieve` before
  prompt assembly; current [app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py)
  still passes `memories=None`.
- [RUNBOOK.md](../RUNBOOK.md) says D4-3 / D4-4 refresh `loneliness_score` before
  D4-2; no `loneliness_updater`, scorer worker, or `LONELINESS_REFRESH_ENABLED`
  setting exists on `main`.
- [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) already records
  the env mismatch for `MEMORY_RETRIEVE_TOP_K`, `MEMORY_RETRIEVE_IN_PROMPT`, and
  `LONELINESS_REFRESH_ENABLED`.

Recommended wording change for RUNBOOK if implementation is not next:

```markdown
D4-2 / D4-3 / D4-4 are target behavior. Current main has retrieval primitives,
prompt rendering slots, and score columns, but the orchestrator injection,
loneliness scorer, and score worker are still pending.
```

## Cursor Handoff For CUR-D8-02

Please update the roadmap using the split above:

1. Keep D4-2 / D4-3 / D4-4 unchecked unless Cursor lands the missing code paths.
2. Mark only D8-2 memory-index subtasks done; keep worker concurrency and P95
   measurement as separate pending subtasks.
3. Keep D8-4 unchecked as a full roadmap item until PR #29, seven-day beta data,
   and token-cost reporting are merged or explicitly removed from scope.
4. If the roadmap UI cannot represent subtasks, prefer "pending / partial" text
   over a green done state.
