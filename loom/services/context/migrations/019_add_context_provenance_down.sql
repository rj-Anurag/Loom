ALTER TABLE context_units DROP CONSTRAINT IF EXISTS ck_context_units_source_type;
ALTER TABLE context_units
    DROP COLUMN IF EXISTS metadata,
    DROP COLUMN IF EXISTS source_session_id,
    DROP COLUMN IF EXISTS source_type;
