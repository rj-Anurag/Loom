ALTER TABLE context_units ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;
UPDATE context_units SET occurred_at = created_at WHERE occurred_at IS NULL;
ALTER TABLE context_units ALTER COLUMN occurred_at SET DEFAULT now(),
    ALTER COLUMN occurred_at SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_context_units_conversation_occurrence
    ON context_units (project_id, source_type, source_session_id, occurred_at, id);
