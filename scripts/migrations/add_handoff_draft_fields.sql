-- P3-16: Add draft fields to handoff_tasks for S/A suspension with Top3 scripts

-- Add draft-related fields to handoff_tasks
ALTER TABLE handoff_tasks
ADD COLUMN IF NOT EXISTS draft_content TEXT,
ADD COLUMN IF NOT EXISTS draft_script_ids JSONB,
ADD COLUMN IF NOT EXISTS draft_created_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS draft_expires_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS countdown_seconds INTEGER DEFAULT 120;

-- Create index for draft expiration queries
CREATE INDEX IF NOT EXISTS idx_handoff_tasks_draft_expires
ON handoff_tasks(draft_expires_at)
WHERE draft_expires_at IS NOT NULL;

-- Create index for S/A level filtering (via users.level)
CREATE INDEX IF NOT EXISTS idx_handoff_tasks_user_level
ON handoff_tasks(user_id);

-- Add comment
COMMENT ON COLUMN handoff_tasks.draft_content IS 'Draft content with Top3 script recommendations';
COMMENT ON COLUMN handoff_tasks.draft_script_ids IS 'Array of script IDs for Top3 recommendations';
COMMENT ON COLUMN handoff_tasks.draft_created_at IS 'Draft creation timestamp';
COMMENT ON COLUMN handoff_tasks.draft_expires_at IS 'Draft expiration timestamp (countdown end)';
COMMENT ON COLUMN handoff_tasks.countdown_seconds IS 'Countdown duration in seconds (default 120s)';