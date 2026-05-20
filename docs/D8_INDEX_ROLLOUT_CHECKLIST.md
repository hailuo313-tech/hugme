# D8 Index Rollout Checklist

This checklist is for deciding whether the D8 memories performance indexes have
already been applied in production, how to apply them safely, and how to roll
back if needed.

It is documentation only. The migration SQL lives in:

- `scripts/migrations/d8-1_memories_btree_indexes.sql`
- `scripts/migrations/d8-2_memories_embedding_ivfflat.sql`

Run all commands from the production checkout unless noted:

```bash
cd /opt/eris
```

## Indexes

| Phase | Index | Migration | Purpose | Query path |
| --- | --- | --- | --- | --- |
| D8-1 | `idx_memories_user_active_created_at` | `d8-1_memories_btree_indexes.sql`; already in `scripts/init.sql` for fresh DBs | Fast active memories by user and recency | loneliness refresh / recent `emotion_tags` windows |
| D8-1 | `idx_memories_user_active_importance_created` | `d8-1_memories_btree_indexes.sql`; already in `scripts/init.sql` for fresh DBs | Fast active memories by user and fallback importance ordering | `memory_retriever` fallback: `ORDER BY importance_score DESC, created_at DESC` |
| D8-2 | `memories_embedding_ivfflat` | `d8-2_memories_embedding_ivfflat.sql` only | Fast vector candidate ordering | `memory_retriever` vector path: `ORDER BY embedding <=> CAST(:qvec AS vector)` |

## Preflight

1. Confirm health:

```bash
curl -fsS http://127.0.0.1:8000/health/detail
docker compose ps
```

2. Confirm a fresh backup exists:

```bash
ls -lh /opt/eris/backups/eris_backup_*.tar.gz | tail -n 3
```

If no recent backup exists, run the existing backup path before continuing:

```bash
PROJECT_ROOT=/opt/eris BACKUP_DIR=/opt/eris/backups /opt/eris/scripts/backup.sh
```

3. Confirm table size and embedding backfill readiness:

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  COUNT(*) AS memories_total,
  COUNT(*) FILTER (WHERE is_active = true) AS active_total,
  COUNT(*) FILTER (WHERE is_active = true AND embedding IS NOT NULL) AS active_embedded,
  COUNT(*) FILTER (WHERE is_active = true AND embedding IS NULL) AS active_pending_embedding
FROM memories;"
```

D8-1 can run at any time. D8-2 is most useful after there are enough non-null
embeddings for IVFFLAT to beat a sequential scan.

4. Check available disk. Index builds need temporary and final index space:

```bash
df -h / /var/lib/docker
docker exec eris-postgres psql -U eris -d eris -c "
SELECT pg_size_pretty(pg_relation_size('memories')) AS memories_table_size;"
```

## Has Production Already Run It?

Use this read-only check:

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  c.relname AS index_name,
  am.amname AS access_method,
  pg_get_indexdef(i.indexrelid) AS definition,
  idx.indisvalid AS is_valid,
  idx.indisready AS is_ready,
  pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size
FROM pg_class c
JOIN pg_index idx ON idx.indrelid = c.oid
JOIN pg_class i ON i.oid = idx.indexrelid
JOIN pg_am am ON am.oid = i.relam
WHERE c.relname = 'memories'
  AND i.relname IN (
    'idx_memories_user_active_created_at',
    'idx_memories_user_active_importance_created',
    'memories_embedding_ivfflat'
  )
ORDER BY i.relname;"
```

Interpretation:

- Missing D8-1 rows: run `d8-1_memories_btree_indexes.sql`.
- Missing D8-2 row: IVFFLAT has not been applied yet.
- `is_valid=false` or `is_ready=false`: a concurrent index build may have failed
  or been interrupted; see rollback / cleanup below.
- Fresh DBs created from `scripts/init.sql` should already have the two D8-1
  B-tree indexes, but not D8-2.

Optional statistics check after running indexes:

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  indexrelname,
  idx_scan,
  idx_tup_read,
  idx_tup_fetch
FROM pg_stat_user_indexes
WHERE relname = 'memories'
  AND indexrelname IN (
    'idx_memories_user_active_created_at',
    'idx_memories_user_active_importance_created',
    'memories_embedding_ivfflat'
  )
ORDER BY indexrelname;"
```

`idx_scan=0` immediately after rollout is normal. It should rise after real
traffic or targeted smoke.

## Execution Order

Run in this order, during a quiet maintenance window:

1. Confirm backup and health.
2. Run D8-1 B-tree/partial indexes.
3. Run `ANALYZE memories;` if it did not complete in the script.
4. Confirm D8-1 rows are valid/ready.
5. Confirm embedding backfill volume.
6. Run D8-2 IVFFLAT only when the vector path is worth indexing.
7. Run `ANALYZE memories;` again.
8. Run read-only verification and a retrieve smoke.

Example using Docker:

```bash
cd /opt/eris

docker exec -i eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 \
  < scripts/migrations/d8-1_memories_btree_indexes.sql

docker exec -i eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 \
  < scripts/migrations/d8-2_memories_embedding_ivfflat.sql
```

Important:

- `CREATE INDEX CONCURRENTLY` cannot run inside an explicit `BEGIN ... COMMIT`.
- Use plain `psql -f` or `docker exec -i ... psql < file`, which runs with
  autocommit.
- `IF NOT EXISTS` makes accidental re-runs mostly safe, but it will not change
  an existing IVFFLAT `lists` value. To retune `lists`, drop and recreate the
  index intentionally.
- Expect some extra CPU, IO, and disk pressure while the index builds.

## Query Correspondence

`app/services/memory_retriever.py` uses:

```sql
WHERE user_id = :uid
  AND is_active = true
  AND importance_score >= :min_imp
  [AND memory_type = ANY(:types)]
  [AND character_id / global scope filter]
```

Vector path:

```sql
AND embedding IS NOT NULL
ORDER BY embedding <=> CAST(:qvec AS vector) ASC
LIMIT :k
```

Fallback path:

```sql
ORDER BY importance_score DESC, created_at DESC
LIMIT :k
```

The D8-1 importance index supports the fallback ordering after user/active
filtering. The D8-2 IVFFLAT index supports cosine candidate ordering on
`embedding`. The D8-1 created-at index supports user/time-window reads used by
loneliness/emotion refresh logic.

## Post-Rollout Verification

1. Confirm indexes are valid and ready using the query in "Has Production
   Already Run It?"

2. Confirm planner stats are refreshed:

```bash
docker exec eris-postgres psql -U eris -d eris -c "ANALYZE memories;"
```

3. Smoke memory retrieval for a user with memories:

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8000/api/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

USER_ID=<user-with-memories>

curl -fsS -X POST "http://127.0.0.1:8000/api/v1/users/$USER_ID/memories/retrieve" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"我最近提过什么重要的事情？","k":5}' \
  | python3 -m json.tool
```

Expected:

- API returns JSON, not 5xx.
- `embedding_used=true` when OpenAI embedding is configured and indexed rows
  exist; fallback may return `embedding_used=false` if embeddings are missing or
  the embedder is unavailable.
- `/health/detail` stays all `ok`.

## 24h Post-Execution Audit

Run this audit 24 hours after the production rollout, or after one real beta
traffic window if traffic is sparse. Fill the note template at the end of this
section with booleans and dates so the rollout can be closed without guessing.

### Audit Checklist

| Item | Command / evidence | Pass | Fail / action |
| --- | --- | --- | --- |
| Health stayed green | `/health/detail` and `docker compose ps` | `api`, `db`, and `redis` are `ok`; containers are healthy/up | Any non-ok health or restart loop. Pause invites and inspect logs before judging index success. |
| Indexes still valid | "Index validity" query below | All applied indexes have `is_valid=true` and `is_ready=true` | Any false value. Treat as interrupted concurrent build; use invalid-index cleanup. |
| Statistics refreshed | `ANALYZE memories;` plus `last_analyze` query below | `last_analyze` or `last_autoanalyze` is after rollout time | Neither timestamp moved after rollout. Run `ANALYZE memories;` and re-check plans. |
| B-tree usage visible | `pg_stat_user_indexes` query below | `idx_scan > 0` for at least one D8-1 index after real traffic or targeted fallback smoke | `idx_scan=0` after targeted fallback smoke. Capture EXPLAIN and check whether query shape changed. |
| IVFFLAT usage visible | `pg_stat_user_indexes` query below | `memories_embedding_ivfflat.idx_scan > 0` after vector smoke with non-null embeddings | `idx_scan=0` after vector smoke. Check row volume, `embedding IS NOT NULL`, and EXPLAIN plan. |
| Fallback plan acceptable | Fallback EXPLAIN sample below | Plan uses `idx_memories_user_active_importance_created` or finishes under threshold | Sequential scan with high cost/latency on production-sized user data. Keep D8-1 but investigate query filters/stats. |
| Vector plan acceptable | Vector EXPLAIN sample below | Plan uses `memories_embedding_ivfflat` or finishes under threshold on small tables | Sequential scan over a large embedded set, or latency over threshold. Consider IVFFLAT `lists` retune on staging. |
| No write regression | App logs and DB health | No new DB timeout/write-lock symptoms during the 24h window | New write latency, lock, or disk-pressure symptoms. Drop D8-2 first if vector index is suspect. |

Thresholds for this MVP:

- Fallback memory query: `Execution Time <= 50 ms` for `LIMIT 30` on a single
  user after warm-up.
- Vector memory query: `Execution Time <= 150 ms` for `LIMIT 30` on a single
  user after warm-up.
- If the table has fewer than 1,000 active memories or fewer than 500 non-null
  embeddings, an index may not be chosen. In that case, pass can be based on
  execution time plus valid/ready index state.

### Index Validity

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  i.relname AS index_name,
  am.amname AS access_method,
  idx.indisvalid AS is_valid,
  idx.indisready AS is_ready,
  pg_size_pretty(pg_relation_size(i.oid)) AS index_size,
  pg_get_indexdef(i.oid) AS definition
FROM pg_class c
JOIN pg_index idx ON idx.indrelid = c.oid
JOIN pg_class i ON i.oid = idx.indexrelid
JOIN pg_am am ON am.oid = i.relam
WHERE c.relname = 'memories'
  AND i.relname IN (
    'idx_memories_user_active_created_at',
    'idx_memories_user_active_importance_created',
    'memories_embedding_ivfflat'
  )
ORDER BY i.relname;"
```

Pass criteria:

- Every index that was intentionally applied is present.
- `is_valid=true` and `is_ready=true` for every present D8 index.

Fail criteria:

- Missing intended index, or any `is_valid=false` / `is_ready=false`.
- Follow "Interrupted `CREATE INDEX CONCURRENTLY`" cleanup before re-running.

### `pg_stat_user_indexes` 24h Snapshot

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  s.indexrelname,
  s.idx_scan,
  s.idx_tup_read,
  s.idx_tup_fetch,
  pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
FROM pg_stat_user_indexes s
WHERE s.relname = 'memories'
  AND s.indexrelname IN (
    'idx_memories_user_active_created_at',
    'idx_memories_user_active_importance_created',
    'memories_embedding_ivfflat'
  )
ORDER BY s.indexrelname;"
```

Pass criteria:

- D8-1: at least one B-tree index has `idx_scan > 0` after real traffic or
  targeted smoke.
- D8-2: `memories_embedding_ivfflat.idx_scan > 0` after a vector smoke on a user
  with embedded memories.
- `idx_tup_read` is not exploding unexpectedly compared with the small `LIMIT`
  query shape.

Fail criteria:

- `idx_scan=0` for an index after a targeted smoke that should exercise it.
- `idx_tup_read` is unexpectedly huge for a small beta user. Capture EXPLAIN
  output and compare filters.

### Analyze Timestamp

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT
  relname,
  last_analyze,
  last_autoanalyze,
  n_live_tup,
  n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'memories';"
```

Pass criteria:

- `last_analyze` or `last_autoanalyze` is after the index rollout time.
- `n_dead_tup` is not growing unexpectedly during the audit window.

Fail criteria:

- No analyze timestamp after rollout. Run `ANALYZE memories;` and rerun the
  EXPLAIN checks.

### Plan Comparison Inputs

Pick one real beta user with memories:

```bash
USER_ID=<user-with-memories>
```

Pick one query vector from an existing embedded memory for that user. This keeps
the EXPLAIN sample read-only and avoids hard-coding external API keys:

```bash
QVEC=$(docker exec eris-postgres psql -U eris -d eris -At -v uid="$USER_ID" -c "
SELECT embedding::text
FROM memories
WHERE user_id = :'uid'
  AND is_active = true
  AND embedding IS NOT NULL
LIMIT 1;")
```

Pass criteria:

- `QVEC` is non-empty before running the vector EXPLAIN sample.

Fail criteria:

- Empty `QVEC`: D8-2 cannot be audited for that user. Choose another user or
  wait for embedding backfill.

### Fallback EXPLAIN Sample

This matches the no-embedding fallback ordering in
`app/services/memory_retriever.py`:

```bash
docker exec eris-postgres psql -U eris -d eris -v uid="$USER_ID" -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, content, memory_type, importance_score, confidence_score,
       emotion_tags, created_at, last_used_at,
       NULL::float AS similarity
FROM memories
WHERE user_id = :'uid'
  AND is_active = true
  AND importance_score >= 0
ORDER BY importance_score DESC, created_at DESC
LIMIT 30;"
```

Pass criteria:

- Plan includes `idx_memories_user_active_importance_created`, or
  `Execution Time <= 50 ms`.
- Buffers do not show a large table-wide read for a single-user query.

Fail criteria:

- Sequential scan over a large `memories` table and `Execution Time > 50 ms`.
- Sort spills to disk. Investigate stats, query filters, and whether the index
  definition matches production query shape.

### Vector EXPLAIN Sample

Run only when `QVEC` is non-empty:

```bash
docker exec eris-postgres psql -U eris -d eris -v uid="$USER_ID" -v qvec="$QVEC" -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, content, memory_type, importance_score, confidence_score,
       emotion_tags, created_at, last_used_at,
       1 - (embedding <=> CAST(:'qvec' AS vector)) AS similarity
FROM memories
WHERE user_id = :'uid'
  AND is_active = true
  AND importance_score >= 0
  AND embedding IS NOT NULL
ORDER BY embedding <=> CAST(:'qvec' AS vector) ASC
LIMIT 30;"
```

Pass criteria:

- Plan includes `memories_embedding_ivfflat`, or `Execution Time <= 150 ms` on a
  small table where PostgreSQL reasonably prefers a sequential scan.
- Returned rows are limited and no disk spill appears in the plan.

Fail criteria:

- Large embedded set, sequential scan, and `Execution Time > 150 ms`.
- IVFFLAT is chosen but still slow. Retune `lists` only after testing on staging
  or a restored backup.

### 24h Audit Note Template

```text
D8 index 24h audit
rollout date:
audit date:
operator:
production commit:
backup file before rollout:

health_ok: true/false
indexes_valid_ready: true/false
analyze_after_rollout: true/false
btree_idx_scan_seen: true/false
ivfflat_applicable: true/false
ivfflat_idx_scan_seen: true/false
fallback_explain_pass: true/false
vector_explain_applicable: true/false
vector_explain_pass: true/false
write_regression_seen: true/false

pg_stat_user_indexes snapshot:
fallback explain execution_time_ms:
vector explain execution_time_ms:
decision: keep / drop D8-2 / rollback indexes / investigate
follow-up:
```

## Rollback / Cleanup

Index rollback is a metadata/storage cleanup, not a data rollback. Dropping
these indexes does not delete memories.

Use `DROP INDEX CONCURRENTLY` outside an explicit transaction:

```bash
docker exec eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 -c \
  "DROP INDEX CONCURRENTLY IF EXISTS memories_embedding_ivfflat;"

docker exec eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 -c \
  "DROP INDEX CONCURRENTLY IF EXISTS idx_memories_user_active_importance_created;"

docker exec eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 -c \
  "DROP INDEX CONCURRENTLY IF EXISTS idx_memories_user_active_created_at;"

docker exec eris-postgres psql -U eris -d eris -c "ANALYZE memories;"
```

Rollback order:

1. Drop D8-2 first if vector retrieval degraded or the IVFFLAT build was
   mis-tuned.
2. Drop D8-1 only if the B-tree indexes caused unexpected disk pressure or
   write overhead.
3. Re-run health and retrieve smoke.

## Mis-Run / Failure Handling

### Re-run accidentally

The scripts use `IF NOT EXISTS`, so a duplicate run should not build duplicate
indexes. Verify with the "Has Production Already Run It?" query and move on.

### Interrupted `CREATE INDEX CONCURRENTLY`

Symptoms:

- Index row exists but `is_valid=false` or `is_ready=false`.
- Future `CREATE INDEX CONCURRENTLY IF NOT EXISTS` may skip because the invalid
  index name already exists.

Cleanup:

```bash
docker exec eris-postgres psql -U eris -d eris -c "
SELECT i.relname, idx.indisvalid, idx.indisready
FROM pg_class c
JOIN pg_index idx ON idx.indrelid = c.oid
JOIN pg_class i ON i.oid = idx.indexrelid
WHERE c.relname = 'memories'
  AND i.relname LIKE '%memories%';"
```

Then drop the invalid index concurrently and rerun the migration:

```bash
docker exec eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 -c \
  "DROP INDEX CONCURRENTLY IF EXISTS <invalid_index_name>;"
```

### Disk pressure during build

If disk alerts fire:

1. Stop the rollout after the current `psql` command returns.
2. Do not start D8-2.
3. Drop any invalid/incomplete index.
4. Preserve logs and backup state.
5. Retry in a larger maintenance window or on a restored staging copy first.

### Wrong IVFFLAT `lists`

`IF NOT EXISTS` will not retune an existing index. If `lists=100` is wrong for
production size, validate on staging or a restored backup first, then:

```bash
docker exec eris-postgres psql -U eris -d eris -v ON_ERROR_STOP=1 -c \
  "DROP INDEX CONCURRENTLY IF EXISTS memories_embedding_ivfflat;"

# Edit migration or run a one-off reviewed command with the chosen lists value.
# Then recreate and ANALYZE.
```

Document the chosen `lists` value in the rollout note.

## Rollout Note Template

```text
D8 index rollout
date:
operator:
backup file:
preflight health:
memories_total / active_embedded:
D8-1 status:
D8-2 status:
ANALYZE completed:
retrieve smoke user_id:
result:
rollback needed:
follow-up:
```
