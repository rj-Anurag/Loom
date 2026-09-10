DROP TRIGGER IF EXISTS trg_event_log_no_update ON event_log;
DROP TRIGGER IF EXISTS trg_event_log_no_delete ON event_log;
DROP FUNCTION IF EXISTS prevent_event_log_mutation();
DROP TABLE IF EXISTS event_log;
DROP TYPE IF EXISTS event_type;
