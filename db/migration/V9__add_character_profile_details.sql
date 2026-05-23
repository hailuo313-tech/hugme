-- Backfill production databases created before structured character profiles.
ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS profile_details JSONB DEFAULT '{}'::jsonb;
