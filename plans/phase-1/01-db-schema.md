---
title: "Phase 1.1 — Database Schema & Migrations"
description: "PostgreSQL schema for context_units, context_edges, event_log, agents, and projects tables. Includes pgvector setup, trust-tier ENUM, and migration runner."
status: pending
dependencies: ["phase-0/02-dev-environment.md"]
---

# Database Schema & Migrations

## Description
Create the core database schema for Loom. This is the foundation of the entire system — every other service depends on it. The schema includes the append-only event log, the context unit graph with vector embeddings, and the agent/project registry.

## Schema Design

### Table: `projects`
```sql
CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    retention_policy TEXT DEFAULT 'archive_after_90_days'
);
```

### Table: `agents`
```sql
CREATE TABLE agents (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID NOT NULL REFERENCES projects(id),
    kind           TEXT NOT NULL CHECK (kind IN ('local', 'cloud', 'browser')),
    credentials_ref TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Table: `context_units`
```sql
CREATE TYPE context_unit_type AS ENUM (
    'message', 'decision', 'artifact_ref', 'task_result', 'summary'
);

CREATE TYPE trust_tier AS ENUM (
    'user', 'agent', 'external_tool'
);

CREATE TABLE context_units (
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

CREATE INDEX idx_context_units_project ON context_units(project_id, created_at DESC);
CREATE INDEX idx_context_units_client_uuid ON context_units(client_uuid);
CREATE INDEX idx_context_units_embedding ON context_units USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_context_units_content_gin ON context_units USING gin(to_tsvector('english', content));
```

### Table: `context_edges`
```sql
CREATE TYPE edge_relation AS ENUM (
    'derived_from', 'supersedes', 'references', 'merged_from'
);

CREATE TABLE context_edges (
    parent_id UUID NOT NULL REFERENCES context_units(id),
    child_id  UUID NOT NULL REFERENCES context_units(id),
    relation  edge_relation NOT NULL,
    PRIMARY KEY (parent_id, child_id, relation)
);

CREATE INDEX idx_context_edges_child ON context_edges(child_id);
CREATE INDEX idx_context_edges_parent ON context_edges(parent_id);
```

### Table: `event_log`
```sql
CREATE TYPE event_type AS ENUM (
    'write', 'merge', 'conflict_flagged'
);

CREATE TABLE event_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    event_type  event_type NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_log_project ON event_log(project_id, created_at ASC);
```

### Table: `pending_branches`
```sql
CREATE TABLE pending_branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_unit_id UUID NOT NULL REFERENCES context_units(id),
    conflict_type   TEXT NOT NULL,
    resolution      TEXT DEFAULT 'pending' CHECK (resolution IN ('pending', 'auto_merged', 'resolved')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Migration Runner

Create `scripts/migrate.sh` that:
1. Reads env vars (DATABASE_URL)
2. Applies SQL migrations in order from `services/context/migrations/`
3. Tracks applied migrations in a `_migrations` table
4. Supports `up` (apply pending) and `down` (rollback last) commands

Migration files:
```
services/context/migrations/
  001_create_projects.sql
  002_create_agents.sql
  003_create_context_units.sql
  004_create_context_edges.sql
  005_create_event_log.sql
  006_create_pending_branches.sql
  007_create_indexes.sql
```

## Acceptance Criteria

- [ ] All migrations apply cleanly with `scripts/migrate.sh up`
- [ ] Rollback works with `scripts/migrate.sh down`
- [ ] `context_units` table has all columns including `trust_tier` and `client_uuid`
- [ ] `event_log` table is append-only (no UPDATE/DELETE triggers)
- [ ] pgvector extension is installed and `vector(1536)` column works
- [ ] Foreign keys enforce referential integrity
- [ ] `client_uuid` has a UNIQUE constraint for idempotency

## TDD Instructions

**Before implementing:** Write integration tests:

```python
def test_create_context_unit():
    # Insert a project, agent, and context_unit
    # Verify the row exists and has correct defaults
    pass

def test_event_log_is_immutable():
    # Verify that UPDATE and DELETE on event_log raise errors
    pass

def test_client_uuid_uniqueness():
    # Insert with same client_uuid twice — second should fail
    pass
```

## Dependencies
- Phase 0.2 (Docker Compose with Postgres+pgvector must be running)
