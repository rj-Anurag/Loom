CREATE TABLE IF NOT EXISTS chat_links (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chat_url    TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    platform    TEXT NOT NULL DEFAULT '',
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_links_project
    ON chat_links(project_id);
