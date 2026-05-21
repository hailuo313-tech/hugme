-- P3-18: Create conversation_script_hits table for async premium chat archiving

-- Create conversation_script_hits table for storing script hit records
CREATE TABLE IF NOT EXISTS conversation_script_hits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    hook VARCHAR(20) NOT NULL,
    script_ids JSONB NOT NULL DEFAULT '[]',
    script_hit_id VARCHAR(128),
    matched BOOLEAN NOT NULL DEFAULT false,
    degradation VARCHAR(100),
    user_level VARCHAR(5),
    platform VARCHAR(20) DEFAULT 'telegram',
    intent_id VARCHAR(128),
    source_message_id UUID,
    trace_id VARCHAR(64),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_conversation ON conversation_script_hits(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_message ON conversation_script_hits(message_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_hook ON conversation_script_hits(hook);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_created_at ON conversation_script_hits(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_conversation_hook ON conversation_script_hits(conversation_id, hook);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_script_hit ON conversation_script_hits(script_hit_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_source_message ON conversation_script_hits(source_message_id);

-- Create trigger for auto-updating updated_at
CREATE OR REPLACE FUNCTION update_conversation_script_hits_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_conversation_script_hits_updated_at ON conversation_script_hits;
CREATE TRIGGER trigger_update_conversation_script_hits_updated_at
    BEFORE UPDATE ON conversation_script_hits
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_script_hits_updated_at();

-- Add comment
COMMENT ON TABLE conversation_script_hits IS 'Conversation script hit records for P3-18 async premium chat archiving';
COMMENT ON COLUMN conversation_script_hits.hook IS 'Script hook name (inbound, consumption, probe, grading, reply, operator, outbound, archive)';
COMMENT ON COLUMN conversation_script_hits.script_ids IS 'Array of matched script IDs';
COMMENT ON COLUMN conversation_script_hits.script_hit_id IS 'Script hit record ID for traceability';
COMMENT ON COLUMN conversation_script_hits.matched IS 'Whether scripts were matched';
COMMENT ON COLUMN conversation_script_hits.degradation IS 'Degradation reason if no match';
COMMENT ON COLUMN conversation_script_hits.source_message_id IS 'Outbound/source message schedule ID when the hit is archived from delivery';
COMMENT ON COLUMN conversation_script_hits.trace_id IS 'Request trace ID for audit correlation';
