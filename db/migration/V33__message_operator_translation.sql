-- Persist operator-facing translations generated from the admin conversation drawer.
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS operator_translation_zh TEXT;

COMMENT ON COLUMN messages.operator_translation_zh IS
    'Simplified Chinese reference translation shown only in admin; not sent to users.';
