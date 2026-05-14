-- D8-2：IVFFLAT cosine index for ORDER BY embedding <=> … (hybrid retrieval hot path).
-- Requires extension "vector" (see scripts/init.sql).
-- Tune lists: rule of thumb lists ≈ sqrt(row_count) for ivfflat; default 100 is a starting point.
-- Re-run after major embedding backfill: DROP INDEX CONCURRENTLY … then recreate if you change lists.

CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_embedding_ivfflat
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

ANALYZE memories;
