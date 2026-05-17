-- P3: structured character profile details for admin-created personas

ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS profile_details JSONB DEFAULT '{}'::jsonb;
