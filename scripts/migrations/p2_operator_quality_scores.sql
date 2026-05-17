CREATE TABLE IF NOT EXISTS operator_quality_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    handoff_task_id UUID REFERENCES handoff_tasks(id) ON DELETE SET NULL,
    operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    reviewer_operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    overall_score INTEGER NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    empathy_score INTEGER CHECK (empathy_score BETWEEN 0 AND 100),
    accuracy_score INTEGER CHECK (accuracy_score BETWEEN 0 AND 100),
    safety_score INTEGER CHECK (safety_score BETWEEN 0 AND 100),
    timeliness_score INTEGER CHECK (timeliness_score BETWEEN 0 AND 100),
    result VARCHAR(30) NOT NULL DEFAULT 'needs_review',
    issue_tags JSONB NOT NULL DEFAULT '[]',
    review_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_operator_created
    ON operator_quality_scores(operator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_handoff
    ON operator_quality_scores(handoff_task_id);

CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_conversation
    ON operator_quality_scores(conversation_id);

CREATE INDEX IF NOT EXISTS idx_operator_quality_scores_result
    ON operator_quality_scores(result);
