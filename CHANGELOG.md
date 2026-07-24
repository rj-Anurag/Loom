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

- **Phase 1.5 — MCP Tool Definitions** (2026-07-24)
  - `ToolRegistry` class that holds and dispatches MCP tool calls bound to a session+project+agent
  - `ReadContextTool` — wraps `read_context()` service with:
    - Full-text search relevance ranking via `task_description` parameter
    - Token-budget enforcement with content truncation
    - Scope filtering (`task` / `onboarding` / `full`)
    - `min_trust_tier` post-filter (user > agent > external_tool)
  - `WriteContextTool` — wraps `write_context()` service with:
    - Deterministic `client_uuid` generation (UUID v5 from `type:content`) for automatic idempotency
    - Auto-computed version from parent lineage when parents are referenced
    - Support for `parent_ids` / `parent_relations` for edge creation
  - `GetProjectSummaryTool` — retrieves summary-type context units via `scope="onboarding"`
  - `MCPTool` base class with `definition()` and `call()` interface matching the MCP tool schema
  - Tools call the Python service layer directly (no HTTP overhead) for co-located agents
  - 10 integration tests covering all 3 tools + registry listing + unknown tool error handling + idempotency + trust_tier filtering + parent versioning
  - 54 total tests, zero regressions

- **Phase 1.6 — Idempotency & Versioning** (2026-07-24)
  - `VersionConflict` exception with structured fields (`context_unit_id`, `claimed_version`, `current_version`, `pending_branch_id`)
  - On version conflict, a `pending_branches` record is created with `conflict_type='version_conflict'` and `resolution='pending'`
  - The `PendingBranch` is persisted (committed) even though the conflicting write is rejected
  - Rich 409 response now includes `current_version`, `claimed_version`, `pending_branch_id`, and `context_unit_id`
  - Service-layer `write_context()` creates the `PendingBranch` record via `session.flush()` before raising `VersionConflict`
  - API router catches `VersionConflict`, commits the session (no other mutations pending at that point), and returns structured JSON
  - 4 integration tests covering: PendingBranch creation on conflict, no branch on successful write, multiple conflicts create multiple branches, and structured response fields
  - 58 total tests, zero regressions

- **Phase 1.7 — Trust-Tier Field Enforcement** (2026-07-24)
  - `_ALLOWED_TRUST_TIERS` mapping: `local`/`cloud` agents can write at `agent`/`external_tool` tiers only; `browser` agents can write at any tier
  - `write_context()` service validates the requested `trust_tier` against the agent's `kind` before processing the write
  - Agents cannot impersonate `user` tier — attempted writes return 403 `TRUST_TIER_DENIED`
  - API router maps `TRUST_TIER_DENIED` to HTTP 403
  - `browser`-kind agents (representing human users via the extension) are the only identity allowed to write `user`-tier context
  - Existing schema (Phase 1.1), write path (Phase 1.2), read ranking (Phase 1.3), and MCP `min_trust_tier` filtering (Phase 1.5) already in place and unchanged
  - 6 integration tests covering: default agent tier, local agent denied at user tier, local agent allowed at agent/external_tool tiers, browser agent allowed at user tier, trust-tier preservation through write-read cycle
  - 64 total tests, zero regressions
