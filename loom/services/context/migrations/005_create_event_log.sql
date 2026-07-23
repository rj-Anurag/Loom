DO $$ BEGIN
    CREATE TYPE event_type AS ENUM (
        'write', 'merge', 'conflict_flagged'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS event_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    event_type  event_type NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutability trigger: prevent UPDATE and DELETE on event_log
CREATE OR REPLACE FUNCTION prevent_event_log_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'event_log is append-only: mutations are not allowed';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_event_log_no_update ON event_log;
CREATE TRIGGER trg_event_log_no_update
    BEFORE UPDATE ON event_log
    FOR EACH ROW EXECUTE FUNCTION prevent_event_log_mutation();

DROP TRIGGER IF EXISTS trg_event_log_no_delete ON event_log;
CREATE TRIGGER trg_event_log_no_delete
    BEFORE DELETE ON event_log
    FOR EACH ROW EXECUTE FUNCTION prevent_event_log_mutation();
