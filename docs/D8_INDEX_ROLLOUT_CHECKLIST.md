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
