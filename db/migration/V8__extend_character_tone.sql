-- Allow admin-defined character tone phrases such as
-- "natural, warm, lightly playful".
ALTER TABLE characters
    ALTER COLUMN tone TYPE VARCHAR(100);
