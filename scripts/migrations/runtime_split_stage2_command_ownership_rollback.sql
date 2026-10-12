-- Rollback for Stage 2 command/ownership tables.
-- Safe because these tables are new, start empty, and are not read by current runtime.

DROP TABLE IF EXISTS runtime_events;
DROP TABLE IF EXISTS telegram_account_ownership;
DROP TABLE IF EXISTS runtime_commands;
DROP TABLE IF EXISTS runtime_instances;
