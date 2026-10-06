CREATE TABLE IF NOT EXISTS removed_sources (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL DEFAULT '',
    agent_id UUID,
    removed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_removed_sources_key
    ON removed_sources (project_id, source_type, source_url, source_session_id,
                        COALESCE(agent_id::text, ''));

ALTER TABLE context_units ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;
ALTER TABLE chat_links ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS project_summaries (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    source_revision TEXT NOT NULL,
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
