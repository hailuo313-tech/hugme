# Roadmap Reconcile D8

This is a fact table for the live roadmap items D4-2 through D4-4 and D8-1,
D8-2, D8-4 versus the current `main` branch.

Scope:

- Source branch checked: `main` at `fcbe35e`.
- Live roadmap checked on 2026-05-14 from `https://hugme2.com/roadmap`.
- This table does not mark roadmap cards done by inference. Each conclusion is
  based on merged code, merged docs, or an explicit PR number.

## Summary

| Roadmap item | Roadmap text | Main / PR evidence | Fact read | Recommendation |
| --- | --- | --- | --- | --- |
| D4-2 | Memory injection into Prompt by `memory_type` group + consistency check | [app/services/memory_retriever.py](../app/services/memory_retriever.py) and PR [#26](https://github.com/hailuo313-tech/hugme/pull/26) prove D4-1 retrieval exists. [app/services/prompt_builder.py](../app/services/prompt_builder.py) can render `L6_MEMORY`. But [app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py) still passes `memories=None` into `build_prompt`; [app/core/config.py](../app/core/config.py) has no `MEMORY_RETRIEVE_IN_PROMPT` field. | Retrieval exists, but automatic prompt injection and consistency check are not present on `main`. RUNBOOK currently describes the desired integration as if it exists. | Split remaining work as D4-2b orchestrator injects Top-K memories into `L6_MEMORY`, and D4-2c consistency check. Downgrade RUNBOOK D4-2 "already wired" wording to target behavior until code lands. |
| D4-3 | `loneliness_score` four-dimension scorer + cold-start strategy | [scripts/init.sql](../scripts/init.sql) defines score columns (`initiation_score`, `emotion_score`, `retention_score`, `dependency_score`, `loneliness_score`, `trigger_threshold`). [app/services/loneliness_updater.py](../app/services/loneliness_updater.py) and [tests/test_loneliness_updater.py](../tests/test_loneliness_updater.py) are now on `main` via PR [#46](https://github.com/hailuo313-tech/hugme/pull/46). [app/services/prompt_builder.py](../app/services/prompt_builder.py) reads `profile.loneliness_score` and renders `L7_CONVERSATION_STATE`. | `loneliness_updater` 已合库，未从 `generate_reply` 调用. [app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py) still calls `build_prompt` with `memories=None`, does not import/call `refresh_loneliness_score`, and [app/core/config.py](../app/core/config.py) has no `LONELINESS_REFRESH_ENABLED` field. | Treat the scorer module/tests as merged, but do not mark D4-3 fully done until the orchestrator/config integration lands. Downgrade RUNBOOK "each turn refreshes `loneliness_score`" wording to target behavior until task card 3 wires it into `generate_reply`. |
| D4-4 | Score update Worker + `trigger_threshold` min-only calculation | [scripts/init.sql](../scripts/init.sql) has `trigger_threshold` and score columns. [app/api/admin.py](../app/api/admin.py) reads `loneliness_score` for admin views. [app/services/loneliness_updater.py](../app/services/loneliness_updater.py) can compute/write a refreshed score when called. No score worker, threshold calculation service, scheduler, or orchestrator call was found under [app/services](../app/services), [app/api](../app/api), or [tests](../tests). | Data fields and a callable score refresh helper exist, but the worker/min-only threshold logic and production call path are not implemented on `main`. | Split remaining work as D4-4a worker/scheduler call path, D4-4b min-only threshold formula, D4-4c handoff/alert trigger integration, D4-4d tests. Do not mark done. |
| D8-1 | Fix D7 beta bugs; issue list clear | Merged ops/baseline docs exist: [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) via PR [#31](https://github.com/hailuo313-tech/hugme/pull/31), [docs/PR_GATES_D8.md](PR_GATES_D8.md) via PR [#37](https://github.com/hailuo313-tech/hugme/pull/37) and PR [#39](https://github.com/hailuo313-tech/hugme/pull/39). Open D8 bug/preflight PRs still exist: PR [#33](https://github.com/hailuo313-tech/hugme/pull/33), PR [#35](https://github.com/hailuo313-tech/hugme/pull/35). | Governance/baseline docs are merged, but "issue list clear" is not proven while D8 bug/preflight PRs are still open. | Split remaining work as D8-1a merge/reject active bugfix PRs, D8-1b maintain issue checklist, D8-1c final smoke proof. Do not mark the broad D8-1 card done yet. |
| D8-2 | Performance tuning: slow-query indexes, worker concurrency; P95 < 2s | Memories index artifacts are merged in PR [#28](https://github.com/hailuo313-tech/hugme/pull/28): [scripts/migrations/d8-1_memories_btree_indexes.sql](../scripts/migrations/d8-1_memories_btree_indexes.sql), [scripts/migrations/d8-2_memories_embedding_ivfflat.sql](../scripts/migrations/d8-2_memories_embedding_ivfflat.sql), and [docs/D8_PERFORMANCE_INDEXES.md](D8_PERFORMANCE_INDEXES.md). Rollout/rollback proof is merged in PR [#36](https://github.com/hailuo313-tech/hugme/pull/36): [docs/D8_INDEX_ROLLOUT_CHECKLIST.md](D8_INDEX_ROLLOUT_CHECKLIST.md). | Slow-query index work is present. Worker concurrency and measured P95 < 2s proof are not visible on `main`. D8-2 should not be treated as fully done unless the roadmap card is narrowed to "memory indexes". | Mark only the index subtask done; keep worker concurrency and P95 measurement as separate pending subtasks. |
| D8-4 | Second beta + data dashboard: D1 retention / score distribution / token cost; seven-day first batch data | First-day metric pack is merged in PR [#34](https://github.com/hailuo313-tech/hugme/pull/34): [docs/BETA_DAY1_METRICS.md](BETA_DAY1_METRICS.md) and [scripts/beta/day1_metrics.sh](../scripts/beta/day1_metrics.sh). PR [#29](https://github.com/hailuo313-tech/hugme/pull/29) is merged and adds [docs/D8_4_BETA_DASHBOARD.md](D8_4_BETA_DASHBOARD.md), [docs/D8_ROUND2_METRICS_SPEC.md](D8_ROUND2_METRICS_SPEC.md), [scripts/beta/d8_4_report.sh](../scripts/beta/d8_4_report.sh), and the RUNBOOK D8-4 section. | Day-1 metrics and the D8-4 report package are on `main`. The roadmap still asks for second beta execution and seven-day data; token cost remains a lower-bound report until provider token usage is persisted. | Mark D8-4a Day-1 metrics and D8-4b report package done. Keep D8-4 partial until seven-day beta data and token-cost hardening/source proof are accepted. |

## PR Status Snapshot

Checked on 2026-05-14 with GitHub PR state:

- PR [#29](https://github.com/hailuo313-tech/hugme/pull/29) `chore(d8-4): add beta dashboard report`: merged into `main`.
- D8 repair/preflight PR [#33](https://github.com/hailuo313-tech/hugme/pull/33) `fix(admin): harden auth guard and fix basePath redirect bugs (D8-DEV-01)`: open.
- D8 repair/preflight PR [#35](https://github.com/hailuo313-tech/hugme/pull/35) `docs(d8-dev-02): add ADMIN_BETA_PREFLIGHT.md -- ops 5-minute UI checklist`: open.
- Other open PRs outside this reconcile decision set: #38, #32, #30, #24, #23, #21, #20, #16.

## RUNBOOK Text To Reconcile

The following RUNBOOK claims read like implementation facts, but current `main`
does not contain the corresponding production call path:

- [RUNBOOK.md](../RUNBOOK.md) says D4-2 calls `memory_retriever.retrieve` before
  prompt assembly; current [app/services/llm_orchestrator.py](../app/services/llm_orchestrator.py)
  still passes `memories=None`.
- [RUNBOOK.md](../RUNBOOK.md) says D4-3 / D4-4 refresh `loneliness_score` before
  D4-2. `loneliness_updater` is now on `main`, but `generate_reply` does not
  call it and `LONELINESS_REFRESH_ENABLED` is still not a real config field.
- [docs/CODEX_PARALLEL_BASELINE.md](CODEX_PARALLEL_BASELINE.md) already records
  the env mismatch for `MEMORY_RETRIEVE_TOP_K`, `MEMORY_RETRIEVE_IN_PROMPT`, and
  `LONELINESS_REFRESH_ENABLED`.

Recommended wording change for RUNBOOK if implementation is not next:

```markdown
D4-2 / D4-3 / D4-4 are target behavior. Current main has retrieval primitives,
prompt rendering slots, score columns, and the loneliness updater helper, but
the orchestrator injection, required config fields, score worker, and threshold
calculation path are still pending.
```

## Cursor Handoff For CUR-D8-02

Please update the roadmap using the split above:

1. Keep D4-2 / D4-3 / D4-4 unchecked unless Cursor lands the missing call paths.
2. Mark only D8-2 memory-index subtasks done; keep worker concurrency and P95
   measurement as separate pending subtasks.
3. Treat PR #29 as merged; keep D8-4 partial until seven-day beta data and
   token-cost hardening/source proof are merged or explicitly removed from scope.
4. If the roadmap UI cannot represent subtasks, prefer "pending / partial" text
   over a green done state.
