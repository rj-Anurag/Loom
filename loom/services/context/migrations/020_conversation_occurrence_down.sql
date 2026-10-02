DROP INDEX IF EXISTS idx_context_units_conversation_occurrence;
ALTER TABLE context_units DROP COLUMN IF EXISTS occurred_at;
