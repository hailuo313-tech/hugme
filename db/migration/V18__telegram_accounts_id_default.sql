-- Ensure telegram_accounts can always generate UUID primary keys.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

ALTER TABLE telegram_accounts
    ALTER COLUMN id SET DEFAULT uuid_generate_v4();
