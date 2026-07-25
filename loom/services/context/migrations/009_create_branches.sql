CREATE TABLE IF NOT EXISTS branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    status          TEXT DEFAULT 'open'
                    CHECK (status IN ('open', 'merging', 'merged', 'abandoned')),
    source_branch_id UUID REFERENCES branches(id),
    created_by      UUID NOT NULL REFERENCES agents(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_at       TIMESTAMPTZ,
    UNIQUE(project_id, name)
);
