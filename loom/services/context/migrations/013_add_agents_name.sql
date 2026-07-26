-- Add nullable name column to agents table.
-- Existing rows get NULL (no default needed).
ALTER TABLE agents ADD COLUMN IF NOT EXISTS name VARCHAR(255);
