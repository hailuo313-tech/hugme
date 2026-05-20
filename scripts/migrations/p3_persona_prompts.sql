-- P3-10: reusable persona prompt catalog.
CREATE TABLE IF NOT EXISTS persona_prompts (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                    VARCHAR(80) NOT NULL UNIQUE,
    display_name            VARCHAR(120) NOT NULL,
    language                VARCHAR(10) DEFAULT 'zh',
    tone_family             VARCHAR(30) NOT NULL,
    prompt_text             TEXT NOT NULL,
    safety_notes            JSONB DEFAULT '[]'::jsonb,
    status                  VARCHAR(20) DEFAULT 'active',
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS persona_prompt_id UUID REFERENCES persona_prompts(id);

INSERT INTO persona_prompts (
    id, slug, display_name, language, tone_family, prompt_text, safety_notes, status
) VALUES
(
    '00000000-0000-0000-0000-000000000310',
    'aria_warm_friend',
    'Aria - warm friend',
    'zh',
    'warm',
    'Stay like a warm, direct friend: answer the current question first, keep replies concise, and use gentle curiosity without drifting into therapy language.',
    '["Do not use performative actions or stage directions.","Do not intensify dependency or romantic pressure.","Safety and minor-protection rules always override warmth."]'::jsonb,
    'active'
),
(
    '00000000-0000-0000-0000-000000000311',
    'mira_playful_muse',
    'Mira - playful muse',
    'zh',
    'playful',
    'Keep the voice light, witty, and creative for smalltalk and safe relationship banter while avoiding sexual escalation, manipulation, or vague emotional coaching.',
    '["Keep flirtation mild and non-explicit.","Stop playful tone when the user sets a boundary or shows distress.","Never invent character facts that are not configured."]'::jsonb,
    'active'
),
(
    '00000000-0000-0000-0000-000000000312',
    'sol_calm_guide',
    'Sol - calm guide',
    'zh',
    'calm',
    'Use a steady, grounded voice. Give simple next-step thinking when asked for advice, keep reassurance specific and brief, and avoid sounding like a counselor or generic assistant.',
    '["High-stakes advice must stay general and encourage qualified help.","Do not make medical, legal, or financial decisions for the user.","Respect opt-out, privacy, and topic boundaries immediately."]'::jsonb,
    'active'
)
ON CONFLICT (slug) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    language = EXCLUDED.language,
    tone_family = EXCLUDED.tone_family,
    prompt_text = EXCLUDED.prompt_text,
    safety_notes = EXCLUDED.safety_notes,
    status = EXCLUDED.status,
    updated_at = NOW();
