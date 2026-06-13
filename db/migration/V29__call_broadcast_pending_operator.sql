-- Allow operator review queue for inbound calls after automated sequence exhausted.

ALTER TABLE call_broadcast_jobs DROP CONSTRAINT IF EXISTS call_broadcast_jobs_status_check;
ALTER TABLE call_broadcast_jobs ADD CONSTRAINT call_broadcast_jobs_status_check
    CHECK (status IN (
        'pending', 'dialing', 'streaming', 'completed', 'failed', 'cancelled', 'pending_operator'
    ));

CREATE INDEX IF NOT EXISTS idx_call_broadcast_jobs_pending_operator
    ON call_broadcast_jobs(status, created_at)
    WHERE status = 'pending_operator';
