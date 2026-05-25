-- Add a Chinese operator-facing translation for English scripts.
-- Runtime matching and outgoing messages continue to use script_templates.content.

ALTER TABLE script_templates
    ADD COLUMN IF NOT EXISTS operator_translation_zh TEXT;

COMMENT ON COLUMN script_templates.operator_translation_zh IS
    'Chinese translation shown only in admin for operators; not sent to users';
