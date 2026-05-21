-- P3-21: conversation_script_hits audit trail for all 8 script_match hooks.

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
    platform VARCHAR(40) DEFAULT 'telegram_real_user',
    intent_id VARCHAR(128),
    source_message_id UUID,
    trace_id VARCHAR(64),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE conversation_script_hits
    ALTER COLUMN script_hit_id TYPE VARCHAR(128) USING script_hit_id::text,
    ALTER COLUMN intent_id TYPE VARCHAR(128) USING intent_id::text,
    ADD COLUMN IF NOT EXISTS source_message_id UUID,
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_conversation
    ON conversation_script_hits(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_message
    ON conversation_script_hits(message_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_hook
    ON conversation_script_hits(hook);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_created_at
    ON conversation_script_hits(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_conversation_hook
    ON conversation_script_hits(conversation_id, hook);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_script_hit
    ON conversation_script_hits(script_hit_id);
CREATE INDEX IF NOT EXISTS idx_conversation_script_hits_source_message
    ON conversation_script_hits(source_message_id);

COMMENT ON TABLE conversation_script_hits IS 'P3-21 audit trail for script_match hooks and archive traceability';
COMMENT ON COLUMN conversation_script_hits.hook IS 'Script hook name: inbound, consumption, probe, grading, reply, operator, outbound, archive';
COMMENT ON COLUMN conversation_script_hits.script_ids IS 'Top matched script template IDs for this hook';
COMMENT ON COLUMN conversation_script_hits.script_hit_id IS 'Primary script hit/template ID for traceability';
COMMENT ON COLUMN conversation_script_hits.matched IS 'Whether a script template was matched';
COMMENT ON COLUMN conversation_script_hits.degradation IS 'Explicit degradation reason when no script was matched';
COMMENT ON COLUMN conversation_script_hits.source_message_id IS 'Outbound/source message schedule ID when archived from delivery';
COMMENT ON COLUMN conversation_script_hits.trace_id IS 'Request trace ID for audit correlation';
