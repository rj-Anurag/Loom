ALTER TABLE agents ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_agents_expiration ON agents(expires_at) WHERE revoked_at IS NULL;
