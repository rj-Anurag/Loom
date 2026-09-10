DROP INDEX IF EXISTS idx_agents_expiration;
ALTER TABLE agents DROP COLUMN IF EXISTS expires_at;
