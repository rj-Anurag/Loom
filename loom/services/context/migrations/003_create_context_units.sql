DO $$ BEGIN
    CREATE TYPE context_unit_type AS ENUM (
        'message', 'decision', 'artifact_ref', 'task_result', 'summary'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE trust_tier AS ENUM (
        'user', 'agent', 'external_tool'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS context_units (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    agent_id    UUID NOT NULL REFERENCES agents(id),
    client_uuid UUID NOT NULL UNIQUE,
    type        context_unit_type NOT NULL,
    trust_tier  trust_tier NOT NULL DEFAULT 'agent',
    content     TEXT NOT NULL,
    embedding   vector(1536),
    version     INT NOT NULL DEFAULT 1,
    branch_id   UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
