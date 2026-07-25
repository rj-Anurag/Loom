-- Add 'system' to the agents.kind check constraint.
-- PostgreSQL does not support ALTER TABLE ... ALTER CONSTRAINT for CHECK
-- constraints, so we must drop and recreate.
-- Drop both the old auto-named constraint (from 002_create_agents.sql)
-- and the renamed one (if migration is re-run).
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_kind_check;
ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_kind;
ALTER TABLE agents ADD CONSTRAINT ck_agents_kind
    CHECK (kind IN ('local', 'cloud', 'browser', 'system'));
