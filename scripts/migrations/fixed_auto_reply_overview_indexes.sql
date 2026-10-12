-- Speed up /admin/fixed-replies operation overview queries.
-- Run this file outside an explicit transaction because CONCURRENTLY is used.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_created
    ON fixed_auto_reply_jobs (created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_updated
    ON fixed_auto_reply_jobs (updated_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_sent
    ON fixed_auto_reply_jobs (sent_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_account_created
    ON fixed_auto_reply_jobs (account_id, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_account_sent
    ON fixed_auto_reply_jobs (account_id, sent_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_rule_status
    ON fixed_auto_reply_jobs (rule_id, status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_jobs_conversation_sent
    ON fixed_auto_reply_jobs (conversation_id, sent_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_deliveries_rule_created
    ON fixed_auto_reply_deliveries (rule_id, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fixed_auto_reply_deliveries_status_created
    ON fixed_auto_reply_deliveries (status, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_fixed_overview_account_created
    ON call_broadcast_jobs (account_id, created_at DESC, status, user_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_fixed_overview_account_started
    ON call_broadcast_jobs (account_id, started_at DESC, status, user_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_broadcast_jobs_fixed_overview_account_ended
    ON call_broadcast_jobs (account_id, ended_at DESC, status, user_id);
