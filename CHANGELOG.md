# Changelog

## v0.1.0 — 2026-07-23

### Added

- **Phase 0 — Project Scaffold** (2026-07-23)
  - Python project structure with FastAPI, SQLAlchemy async, asyncpg, pgvector
  - Docker Compose for Postgres+pgvector and Redis
  - `loom serve` daemon entry point
  - `@loom` CLI integration pattern established
  - Browser extension bridge architecture designed (one-tap linking model)

- **Phase 1.1 — Database Schema & Migrations** (2026-07-23)
  - 7 PostgreSQL tables: `projects`, `agents`, `context_units`, `context_edges`, `event_log`, `pending_branches`, `_migrations`
  - PostgreSQL ENUM types: `context_unit_type`, `trust_tier`, `edge_relation`, `event_type`
  - pgvector `vector(1536)` column for embeddings
  - Append-only `event_log` with BEFORE UPDATE/DELETE triggers
  - UNIQUE constraint on `context_units.client_uuid` for idempotency
  - CHECK constraint on `pending_branches.resolution`
  - CHECK constraint on `agents.kind`
  - Foreign key referential integrity across all tables
  - 7 numbered migration SQL files in `loom/services/context/migrations/`
  - 7 SQLAlchemy ORM models matching the migration SQL schema
  - Migration runner script (`scripts/migrate.sh`) with tracking table
  - 17 integration tests covering table existence, columns, constraints, CRUD, immutability, idempotency
  - asyncpg connection pool configuration with `pool_pre_ping`
