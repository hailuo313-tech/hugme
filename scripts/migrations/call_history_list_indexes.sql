-- Speed up /call-broadcast/admin/call-history list joins and ordering.
-- Run outside an explicit transaction because CONCURRENTLY is used.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_external_id
    ON users (external_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_call_at_desc
    ON call_broadcast_jobs (
        (COALESCE(ended_at, started_at, created_at)) DESC
    );
