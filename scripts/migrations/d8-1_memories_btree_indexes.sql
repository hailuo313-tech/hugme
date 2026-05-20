-- D8-1：accelerate memories filter + time order + importance fallback ordering.
-- Safe to re-run (IF NOT EXISTS). Use CONCURRENTLY to avoid long write locks on busy DBs.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_user_active_created_at
    ON memories (user_id, created_at DESC)
    WHERE is_active = true;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_user_active_importance_created
    ON memories (user_id, importance_score DESC, created_at DESC)
    WHERE is_active = true;

ANALYZE memories;
