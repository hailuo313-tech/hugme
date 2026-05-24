-- Keep character tone aligned with the admin API validation limit.
ALTER TABLE characters
    ALTER COLUMN tone TYPE VARCHAR(100);
