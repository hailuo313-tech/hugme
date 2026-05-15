# D8-2 Performance Proof

This document records what is proven for D8-2 and what still needs Cursor or a
release owner before the roadmap can honestly say `P95 < 2s` is done.

Snapshot:

- Checked at: 2026-05-14 PT / 2026-05-15 UTC.
- Source branch checked: `origin/main` at `6fa7c12`.
- Production check was read-only: no migration, no data write, no server file
  edit.

## D8-2a Index Rollout

Production has all three D8 memory indexes present, valid, and ready:

| Index | Valid | Ready | Size | Notes |
| --- | --- | --- | --- | --- |
| `idx_memories_user_active_created_at` | true | true | 16 kB | D8-1 B-tree / partial index. |
| `idx_memories_user_active_importance_created` | true | true | 16 kB | D8-1 fallback ordering index. |
| `memories_embedding_ivfflat` | true | true | 1608 kB | D8-2 IVFFLAT cosine index, `lists=100`. |

Production memory volume at the same check:

| Metric | Value |
| --- | ---: |
| `memories` total | 3 |
| active memories | 3 |
| active memories with non-null `embedding` | 0 |
| active memories pending embedding | 3 |

`pg_stat_user_indexes.idx_scan` was `0` for all three D8 indexes at the
snapshot. This is expected with only three active rows and no embedded rows; it
means the migration is present, not that the vector path has proven useful yet.

## D8-2b Worker Concurrency And Risk

Current code/config facts:

- `app/Dockerfile` starts uvicorn with `--workers 2`.
- `embedding_worker.start_scheduler()` runs in FastAPI lifespan, so each worker
  process can create a scheduler when enabled.
- `run_one_tick()` takes PostgreSQL advisory lock `6300410`; only one process
  should process a batch at a time even when multiple API workers schedule it.
- APScheduler also has `max_instances=1` per process and `coalesce=True`.
- Default config is `EMBEDDING_BATCH_SIZE=32`, `EMBEDDING_POLL_SECONDS=30`,
  `EMBEDDING_WORKER_ENABLED=True`.
- Production container did not expose `OPENAI_API_KEY` or `EMBEDDING_*`
  overrides at this check, so the embedding worker cannot backfill vectors.

Risk notes:

- Turning on `OPENAI_API_KEY` enables real embedding calls. Keep batch size at
  32 until queue depth and provider latency are observed.
- Larger batches increase provider timeout/blast radius. Prefer increasing
  poll frequency only after confirming API CPU, DB connections, and provider
  rate limits have headroom.
- With two uvicorn workers, duplicated schedulers are acceptable only because of
  the advisory lock. If future worker code removes that lock, duplicate
  processing and rate-limit pressure become likely.
- IVFFLAT should not be judged until there are enough non-null embeddings to
  exercise vector retrieval. Today it is installed but effectively idle.

## D8-2c Reproducible P95 Probe

Added script:

```powershell
$env:ERIS_BASE_URL = "https://hugme2.com"
$env:ERIS_USER_ID = "<safe beta user id with memories>"
$env:D8_2_REQUESTS = "30"
$env:D8_2_CONCURRENCY = "1"
python scripts/perf/d8_2_retrieval_load.py
```

The probe calls:

```text
POST /api/v1/users/{user_id}/memories/retrieve
```

It prints client-side latency percentiles plus the app-returned `latency_ms`.

### 2026-05-14 PT Smoke Result

Parameters:

- target: `https://hugme2.com`
- requests: 30
- concurrency: 1
- sample production user: one beta user with 3 active memories
- endpoint result mode: fallback, not vector

Result:

| Metric | Value |
| --- | ---: |
| HTTP success | 30 / 30 |
| client P50 | 350.4 ms |
| client P95 | 702.9 ms |
| client P99 | 880.3 ms |
| client max | 1053.3 ms |
| app-reported P95 | 2.5 ms |
| `embedding_used` | false |
| `fallback_reason` | `OPENAI_API_KEY_MISSING` |
| `candidates_scanned` | 3 |

Interpretation:

- Fallback retrieval path is under 2s in this small production smoke.
- Vector retrieval P95 is not proven because production has zero non-null
  embeddings and the API container has no embedding API key configured.
- Do not mark full D8-2 green yet. Honest roadmap wording is:
  `D8-2a indexes applied; fallback P95 smoke <2s; vector P95 pending embedding backfill.`

## Next Step To Reach Full D8-2

1. Configure `OPENAI_API_KEY` for the API container, or choose a staging
   environment with embeddings enabled.
2. Let `embedding_worker` backfill a meaningful number of active memories.
3. Re-run `scripts/perf/d8_2_retrieval_load.py` with `embedding_used=true`.
4. Capture `pg_stat_user_indexes` again and confirm either
   `memories_embedding_ivfflat.idx_scan > 0` or a documented small-table reason
   for a sequential scan with latency still below threshold.
