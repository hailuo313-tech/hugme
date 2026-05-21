-- P3-01: script_templates table and initial script material categories.

CREATE TABLE IF NOT EXISTS script_template_categories (
    key VARCHAR(40) PRIMARY KEY,
    display_name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO script_template_categories (key, display_name, description, sort_order)
VALUES
    ('greeting', 'Greeting', 'Openers, warm welcomes, and re-entry prompts.', 10),
    ('conversion', 'Conversion', 'VIP value, pricing, benefits, and post-payment copy.', 20),
    ('refusal', 'Refusal', 'Boundary-safe declines, blocked requests, and policy-safe alternatives.', 30),
    ('probe', 'Probe', 'Profile completion prompts for age, country, preference, and context.', 40),
    ('fallback', 'Fallback', 'Safe default responses when no specific template is matched.', 50)
ON CONFLICT (key) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = NOW();

CREATE TABLE IF NOT EXISTS script_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category_key VARCHAR(40) NOT NULL REFERENCES script_template_categories(key),
    title VARCHAR(160) NOT NULL,
    language VARCHAR(10) NOT NULL DEFAULT 'zh',
    channel VARCHAR(40) NOT NULL DEFAULT 'telegram_real_user',
    user_level VARCHAR(1) CHECK (user_level IN ('S', 'A', 'B', 'C', 'D')),
    chat_route VARCHAR(30) CHECK (chat_route IN ('manual_premium', 'ai_assisted', 'ai_auto')),
    persona_slug VARCHAR(80),
    hook VARCHAR(40),
    content TEXT NOT NULL,
    variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    safety_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'archived')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_script_templates_category_status
    ON script_templates(category_key, status);

CREATE INDEX IF NOT EXISTS idx_script_templates_route_hook
    ON script_templates(chat_route, hook);

CREATE INDEX IF NOT EXISTS idx_script_templates_language_channel
    ON script_templates(language, channel);
