DROP TABLE IF EXISTS project_summaries;
DROP TABLE IF EXISTS removed_sources;
ALTER TABLE context_units DROP COLUMN IF EXISTS removed_at;
ALTER TABLE chat_links DROP COLUMN IF EXISTS removed_at;
