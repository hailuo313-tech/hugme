-- P3-13: Create message_schedules table for pending queue with send_at support
-- This table stores messages that need to be sent at specific times

CREATE TABLE IF NOT EXISTS message_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(128) NOT NULL,
    external_user_id VARCHAR(128) NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    platform VARCHAR(20) NOT NULL DEFAULT 'telegram_real_user',
    account_id VARCHAR(64),
    chat_id BIGINT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    send_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    priority INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    trace_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT check_message_schedules_status CHECK (status IN ('pending', 'scheduled', 'sending', 'sent', 'failed'))
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_message_schedules_user_id ON message_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_message_schedules_external_user_id ON message_schedules(external_user_id);
CREATE INDEX IF NOT EXISTS idx_message_schedules_status ON message_schedules(status);
CREATE INDEX IF NOT EXISTS idx_message_schedules_send_at ON message_schedules(send_at);
CREATE INDEX IF NOT EXISTS idx_message_schedules_user_status ON message_schedules(user_id, status);
CREATE INDEX IF NOT EXISTS idx_message_schedules_send_at_status ON message_schedules(send_at, status);
CREATE INDEX IF NOT EXISTS idx_message_schedules_priority_created ON message_schedules(priority, created_at);

-- Create trigger for auto-updating updated_at
CREATE OR REPLACE FUNCTION update_message_schedules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_message_schedules_updated_at ON message_schedules;
CREATE TRIGGER trigger_update_message_schedules_updated_at
    BEFORE UPDATE ON message_schedules
    FOR EACH ROW
    EXECUTE FUNCTION update_message_schedules_updated_at();

-- Add comment
COMMENT ON TABLE message_schedules IS 'Message schedule table for P3-13: Redis pending queue + send_at';
COMMENT ON COLUMN message_schedules.send_at IS 'Scheduled send time (NULL for immediate send)';
COMMENT ON COLUMN message_schedules.priority IS 'Message priority (higher = more urgent)';