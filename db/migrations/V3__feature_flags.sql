-- P5-09: Feature Flag System for Gradual Rollout by User Level
-- 支持按用户等级进行灰度切流

-- Feature flags 表
CREATE TABLE IF NOT EXISTS feature_flags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT FALSE,
    rollout_type VARCHAR(20) NOT NULL DEFAULT 'all', -- all, percentage, level, user_list
    rollout_percentage INTEGER DEFAULT 0, -- 0-100, for percentage type
    target_levels VARCHAR(100), -- comma-separated levels (S,A,B,C,D), for level type
    target_user_ids TEXT, -- comma-separated user IDs, for user_list type
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100)
);

-- Feature flag audit log 表
CREATE TABLE IF NOT EXISTS feature_flag_audit_log (
    id SERIAL PRIMARY KEY,
    feature_flag_id INTEGER REFERENCES feature_flags(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL, -- created, updated, enabled, disabled, deleted
    old_value JSONB,
    new_value JSONB,
    changed_by VARCHAR(100) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason TEXT
);

-- 创建索引
CREATE INDEX idx_feature_flags_name ON feature_flags(name);
CREATE INDEX idx_feature_flags_enabled ON feature_flags(enabled);
CREATE INDEX idx_feature_flag_audit_log_flag_id ON feature_flag_audit_log(feature_flag_id);
CREATE INDEX idx_feature_flag_audit_log_action ON feature_flag_audit_log(action);

-- 插入默认的 feature flags
INSERT INTO feature_flags (name, description, enabled, rollout_type, target_levels, created_by) VALUES
('new_ai_model', 'Enable new AI model for processing', FALSE, 'level', 'S', 'system'),
('enhanced_matching', 'Enhanced script matching algorithm', FALSE, 'percentage', NULL, 'system'),
('real_time_translation', 'Real-time message translation', FALSE, 'level', 'S,A', 'system'),
('advanced_analytics', 'Advanced analytics dashboard', FALSE, 'all', NULL, 'system'),
('beta_features', 'Beta features for testing', FALSE, 'user_list', NULL, 'system')
ON CONFLICT (name) DO NOTHING;

-- 创建更新时间触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_feature_flags_updated_at BEFORE UPDATE ON feature_flags
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 创建审计触发器
CREATE OR REPLACE FUNCTION log_feature_flag_changes()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO feature_flag_audit_log (feature_flag_id, action, new_value, changed_by, reason)
        VALUES (NEW.id, 'created', row_to_json(NEW), NEW.created_by, 'Initial creation');
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.enabled != NEW.enabled THEN
            INSERT INTO feature_flag_audit_log (feature_flag_id, action, old_value, new_value, changed_by, reason)
            VALUES (NEW.id, CASE WHEN NEW.enabled THEN 'enabled' ELSE 'disabled' END, row_to_json(OLD), row_to_json(NEW), NEW.updated_by, 'Status change');
        ELSE
            INSERT INTO feature_flag_audit_log (feature_flag_id, action, old_value, new_value, changed_by, reason)
            VALUES (NEW.id, 'updated', row_to_json(OLD), row_to_json(NEW), NEW.updated_by, 'Configuration update');
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO feature_flag_audit_log (feature_flag_id, action, old_value, changed_by, reason)
        VALUES (OLD.id, 'deleted', row_to_json(OLD), 'system', 'Record deletion');
        RETURN OLD;
    END IF;
END;
$$ language 'plpgsql';

CREATE TRIGGER feature_flag_audit_trigger
    AFTER INSERT OR UPDATE OR DELETE ON feature_flags
    FOR EACH ROW EXECUTE FUNCTION log_feature_flag_changes();