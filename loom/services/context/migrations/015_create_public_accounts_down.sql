DROP INDEX IF EXISTS idx_agents_active_credentials;
DROP INDEX IF EXISTS idx_agents_created_by_user_id;
ALTER TABLE agents DROP COLUMN IF EXISTS revoked_at;
ALTER TABLE agents DROP COLUMN IF EXISTS last_used_at;
ALTER TABLE agents DROP COLUMN IF EXISTS key_hint;
ALTER TABLE agents DROP COLUMN IF EXISTS created_by_user_id;
DROP TABLE IF EXISTS project_memberships;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS users;
