-- P2: 话术库 scripts 表创建迁移
-- PR #76 后端 API 已就绪，此脚本补充数据库 DDL
CREATE TABLE IF NOT EXISTS scripts (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    character_id            UUID,
    language                VARCHAR(10) DEFAULT 'en',
    relationship_stage      VARCHAR(10),
    emotion_state           VARCHAR(30),
    loneliness_score_min    FLOAT DEFAULT 0,
    loneliness_score_max    FLOAT DEFAULT 100,
    script_type             VARCHAR(30),
    content                 TEXT NOT NULL,
    risk_level              VARCHAR(10) DEFAULT 'low',
    conversion_goal         VARCHAR(50),
    review_status           VARCHAR(20) DEFAULT 'draft',
    forbidden_scenarios     JSONB DEFAULT '[]',
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);
