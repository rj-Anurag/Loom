# Changelog

## v0.1.0 — 2026-07-24

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

- **Phase 1.2 — Context Service: Write Path** (2026-07-24)
  - Auth middleware (`loom/api/auth.py`) with Bearer token → Agent lookup
  - Context write service (`loom/services/context/service.py`) with transactional write:
    - Project and agent-belonging validation
    - Idempotency enforcement via `client_uuid` lookup
    - Version-conflict detection (incoming version must equal `max(parent.version) + 1`)
    - Context edge creation for parent references
    - Event-log append for every write
  - `POST /v1/projects/{id}/context` endpoint with Pydantic request/response models
  - 11 integration tests covering success path, idempotency, version conflicts, event logging, edges, validation errors, authorization, and cross-project access
  - First-class `ContextUnitResponse` model with OpenAPI schema generation
  - 30 total tests, zero regressions

- **Phase 1.3 — Context Service: Read Path** (2026-07-24)
  - Keyword-based retrieval using PostgreSQL full-text search (`to_tsvector` + `plainto_tsquery`)
  - GIN-index-backed search on `context_units.content` (index from Phase 1.1)
  - Ranking formula: `0.4 * ts_rank + 0.3 * recency + 0.3 * trust_tier_weight`
  - Token-budget-aware packing with content truncation (4 chars ≈ 1 token)
  - Scope filtering: `onboarding` (summaries only), `task` (all types), `full`
  - `GET /v1/projects/{id}/context` endpoint with `query`, `budget`, `scope` parameters
  - Full Pydantic response model (`ReadContextResponse`, `ReadContextUnitModel`) with OpenAPI schema
  - Batch parent-edge lookup per result set
  - 11 integration tests covering keyword search, empty query, budget adherence, scope filtering, ranking order, authorization, cross-project access, and parent edges
  - 41 total tests, zero regressions

- **Phase 1.4 — Event Log (Append-Only Ledger)** (2026-07-24)
  - Enriched write event payload: `trust_tier`, `content_preview` (200-char truncation), `content_hash` (SHA-256), `parent_ids`, `parent_relations`
  - Content integrity via SHA-256 hash of the unit content in every event payload
  - `rebuild_projections()` service function that reconstructs `context_units` + `context_edges` from event log replay
  - Rebuild is idempotent: running it multiple times produces the same result
  - Chronological event ordering verified
  - 5 integration tests covering enriched payload, hash verification, event ordering, content_preview truncation, and full graph rebuild
  - 46 total tests, zero regressions
