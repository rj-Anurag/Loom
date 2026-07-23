CREATE TABLE IF NOT EXISTS agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    kind            TEXT NOT NULL CHECK (kind IN ('local', 'cloud', 'browser')),
    credentials_ref TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
