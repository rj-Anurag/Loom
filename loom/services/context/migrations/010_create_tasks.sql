CREATE TABLE IF NOT EXISTS tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'pending'
                CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
    assigned_to UUID REFERENCES agents(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
