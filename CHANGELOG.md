# Changelog

## Unreleased

- Added a Render Blueprint for the free MVP deployment path with FastAPI,
  PostgreSQL 16, and Redis-compatible Key Value wiring.
- Added a hosted migration runner and production API entrypoint so migrations
  run through `DATABASE_URL` before Uvicorn starts.
- Normalized standard hosted Postgres URLs to SQLAlchemy's asyncpg driver URL
  and declared the required `pgvector` Python dependency.
- Backfill complete pre-existing browser conversations when linking by combining
  mixed-generation chat selectors, materializing lazy-loaded older turns, and
  using project-scoped replay IDs when a conversation moves between projects.
- Fixed extension linking after access verification, including the conflicting
  dropdown/direct-ID state shown by the popup.
- Made initial chat-history capture reliable for already-open tabs, retry-safe
  on extension messaging failures, and idempotent without dropping repeated
  messages at different conversation positions.
- Added a project-authorized, cursor-paginated context history endpoint so the
  dashboard can display the complete archive without a 32k-token/100-item cap.
- Included dashboard and migration assets in built Python wheels.
- Moved the heavyweight local sentence-transformers/PyTorch stack to the
  `local-embeddings` optional extra so the default API image stays lean.
- Aligned the documented `local` embedding-provider setting with runtime
  configuration, retained the legacy alias, and reject unknown providers
  instead of silently falling back to test embeddings.
- Hardened agent authentication with opaque hashed API keys while retaining
  opt-in legacy UUID-token compatibility for existing installations.
- Enforced project ownership for context parents, tasks, branches, conflicts,
  and chat links; branch merges now use explicit `branch_id` membership.
- Persisted context provenance URLs and full event-log content for reliable
  projection rebuilds, with migration `014_add_context_source_url.sql`.
- Aligned local embeddings with the shared 1536-dimensional pgvector schema.
- Removed the committed extension credential and refreshed the dashboard with a
  Vercel/shadcn-inspired dark visual system.
- Added native Claude Code MCP plus `/loom` installation, Codex MCP/`AGENTS.md`
  setup, and a single `loom init` project/key onboarding flow.
- Added semantic capture adapters for Claude, ChatGPT, DeepSeek, and Perplexity,
  including role-preserving idempotency and an offline retry queue.
- Protected first-run credential bootstrap with an operator token in production
  and restricted project creation to that identity while retaining
  zero-configuration local development.
- Added a production container image, deterministic migration rollback scripts,
  dependency readiness checks, and replaced the fake deploy workflow with an
  executable image validation job.
- Added a vendor-neutral production Compose topology for the API, embedding
  worker, and summarizer; application containers now run as a non-root user.

## Unreleased — 2026-08-24

### Fixed & Enhanced

- **Extension Chat History Sync & Dashboard Visualization**:
  - `extension/content.js`: Rescan and sync all pre-existing DOM chat messages upon linking a chat session to a Loom project.
  - `loom/services/context/service.py`: Preserved timestamp sequence for chronological context reads when no search query is specified (preventing score-based role splitting).
  - `loom/web/dashboard.html`: Enhanced dashboard context feed with distinct **👤 Human Message** vs **🤖 AI Message** styling, multi-line pre-wrap rendering, expandable message toggles, and conversation flow sorting.

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

- **Phase 1.8 — Basic Coordination** (2026-07-24)
  - Entity extraction (`merge.py`): pulls file paths, function names, imports, URLs from context content
  - Overlap detection (`merge.py`): compares two context units for overlapping entities
  - Version-conflict handler updated (`service.py`): when two agents write to the same parent at the same version:
    - No existing siblings → plain version conflict (standard `PendingBranch`)
    - Overlapping content → `PendingBranch` conflict with rich 409
    - Non-overlapping content → auto-merge: adjusts version and creates a `summary`-type merge unit with `merged_from` edges to both siblings, plus an event-log `merge` event
  - Conflict management API endpoints (`conflicts.py`):
    - `GET /v1/projects/{id}/conflicts` — list pending branches for a project
    - `POST /v1/projects/{id}/conflicts/{branch_id}/resolve` — set resolution to `merged` or `discarded`
  - 7 integration tests covering: entity extraction, overlap detection (true/false), non-overlapping auto-merge, overlapping conflict creation, conflict list endpoint, conflict resolve endpoint
  - 71 total tests, zero regressions

- **Phase 1.9 — Async Embedding Pipeline** (2026-07-24)
  - Redis-backed async embedding job queue (`queue.py`): LPUSH jobs to `embedding:queue` after write commits
  - Fire-and-forget enqueue in `service.py`: post-commit hook calls `enqueue_embedding_job()` — Redis failures never mask successful writes
  - Pluggable embedding providers (`providers.py`):
    - `EmbeddingProvider` protocol with `async embed(text) → list[float] | None`
    - `StubProvider`: deterministic L2-normalized 1536-d vector from content hash (default, always available)
    - `OpenAIProvider`: calls `text-embedding-3-small` via `openai.AsyncOpenAI` (opt-in)
    - `from_config()` factory driven by `settings.embedding_provider`
  - Standalone embedding worker (`embedding_worker.py`):
    - `process_embedding_job()`: ORM-based fetch → compute → UPDATE `context_units.embedding`
    - `recover_inprogress()`: drains orphaned `embedding:inprogress` jobs back to queue on startup
    - SIGTERM graceful shutdown with drain-before-exit
    - Worker loop: `BRPOPLPUSH` with 30s timeout, retry up to 3 attempts, then DLQ
  - Dead-letter queue (`dlq.py`): `count_dlq()`, `list_dlq()`, `replay_dlq()` — atomically move items back to main queue
  - Worker entrypoint script (`scripts/run-embedding-worker.sh`)
  - 17 integration tests covering: StubProvider (dimension, determinism, normalization, empty-input), queue enqueue (truncation, redis-down), write-path integration, worker processing, nonexistent-unit skip, error propagation, DLQ management, in-progress recovery
  - 90 total tests, zero regressions

## v0.2.0 — 2026-07-25

### Added

- **Phase 1.10 — Local Agent Prototype** (2026-07-24)
  - `LoomClient` — async HTTP client wrapping all Loom API endpoints
  - `GroqLLM` — LLM provider using Groq's Mixtral-8x7b, Llama-3, and Gemma models
  - `LocalAgent` — single-message loop: project lookup → read context → LLM call → write response → emit event
  - Agent CLI entry point at `loom/scripts/run_local_agent.py`
  - 7 integration tests covering: agent lifecycle, MCP tool invocation, event emission
  - 97 total tests, zero regressions

- **Phase 1.11 — Browser Extension** (2026-07-24)
  - Backend: `chat_links` model, project listing/creation API endpoints
  - Frontend: Manifest V3 extension with content script, popup UI, background service worker
  - Extension API endpoint for setup/linking
  - Popup UX with improved storage and reliable message sync
  - 4 integration tests for chat_links and extension API
  - 101 total tests, zero regressions

- **Phase 1.12 — Concurrent Merge Load Tests** (2026-07-24)
  - 3-agent concurrent write simulation with conflict detection
  - Latency measurement and P95 tracking
  - 1 load test verifying concurrent merge safety
  - 102 total tests, zero regressions

- **Phase 2.1 — Full Coordination Service** (2026-07-25)
  - **Redis distributed locks** (`loom/services/coordination/locks.py`):
    - Atomic `SET NX EX` lock acquire with sorted UUID ordering (deadlock prevention)
    - All-or-nothing multi-lock acquire (release all on any failure)
    - Lua-script-based lock release with ownership verification
    - Exponential backoff on contention (3 retries)
    - Graceful Redis-down fallback (disables locking, allows operations to proceed)
  - **Git-style Branch CRUD + Merge** (`loom/services/coordination/branches.py`):
    - Branch creation with unique constraint on `(project_id, name)`
    - Branch listing with optional status filter
    - Merge branches to main with full context unit version bumping
    - Overlap detection reusing Phase 1.8 merge logic
    - PendingBranch creation on merge conflict
  - **Full Task Lifecycle** (`loom/services/coordination/tasks.py`):
    - Task creation, listing, and retrieval
    - Assignment, start, complete, fail with validated state transitions
    - Optional branch linking via `start_task`
  - **CoordinationService** (`loom/services/coordination/service.py`):
    - Unified public API wrapping locks, branches, and tasks
  - **Write Path Integration** (`loom/services/context/service.py`):
    - Lock-before-version-check ordering to prevent TOCTOU race conditions
    - `branch_id` passthrough on context unit writes
    - Lock release after transaction commit
  - **API Endpoints** (14 new endpoints):
    - Branches: `POST|GET /{project_id}/branches`, `GET /{project_id}/branches/{id}`, `POST /{project_id}/branches/{id}/merge`
    - Tasks: `POST|GET /{project_id}/tasks`, `GET /{project_id}/tasks/{id}`, `POST assign/start/complete/fail`
    - Conflicts: extended with `branch_id` in responses
  - **Database Migrations**: 3 new migration files (branches, tasks, PendingBranch extensions)
  - **Security Hardening**:
    - Project-level authorization on all new endpoints (`_verify_project_access`)
    - `max_length` constraints on branch names and content fields
    - Strict UUID typing in Pydantic models (`branch_id`, `parent_ids`)
    - All endpoints authenticated via Bearer token
  - 150 total tests, zero regressions

- **Phase 2.2 — Hierarchical Summarization** (2026-07-25)
  - **LLM Provider protocol** (`loom/services/retrieval/providers.py`):
    - `LLMProvider` protocol with `async def summarize(units) -> str`
    - `StubLLMProvider` — deterministic concatenation for tests (always available)
    - `GroqLLMProvider` — Groq API-backed summarization via `mixtral-8x7b-32768`
    - `from_llm_config()` factory reading `settings.summarization_provider`
    - Lazy `import groq` inside method — importable without the package installed
    - Prompt-injection mitigation via XML boundary markers and per-unit 4K char limit
  - **Grouping strategy** (`loom/services/retrieval/grouping.py`):
    - Time-window grouping (configurable: 10 min default, 50 units max per group)
    - Deterministic `client_uuid` via `uuid.uuid5(SUMMARY_NS, sorted_ids)` for idempotency
    - Trust-tier inheritance (summary inherits highest trust tier from source units)
    - Filters out units already covered by a `supersedes` edge
  - **Summarization worker** (`loom/services/retrieval/summarizer.py`):
    - `run_summarization_cycle()` — full cycle: lock → group → LLM → write_context → release
    - Project-level Redis lock (`summarize:{project_id}`) with unique token + Lua compare-and-delete
    - Per-group error isolation — a single group failure doesn't abort the cycle
    - `run_summarization_loop()` — asyncio periodic loop with SIGTERM graceful shutdown
    - Summarizer agent identity (`kind="system"`) with full trust-tier write privileges
  - **Read path score boost** (`loom/services/context/service.py`):
    - Flat +0.15 bonus for summary-type units in `_compute_score()` (both Python and SQL paths)
    - Summary units rank above their originals without dominating the formula
  - **Database Migration**: `012_update_agents_kind_check.sql` — adds `'system'` to agents.kind constraint
  - **Entrypoint**: `scripts/run-summarizer.sh`
  - **New settings**: `summarization_window_minutes=10`, `summarization_max_units_per_group=50`, `summarization_min_units=5`, `summarization_provider="stub"`
  - 24 integration tests covering: LLM providers, grouping, full summarization cycle, idempotency, Redis locking, originals preserved, score boost
  - 174 total tests, zero regressions

- **Phase 2.3 — Hybrid Search (Vector + Keyword RRF Fusion)** (2026-07-25)
  - **New module:** `loom/services/retrieval/search.py` (513 lines) — vector + keyword search with Reciprocal Rank Fusion
  - **Query encoding** (`encode_query`): module-level singleton `EmbeddingProvider` with fallback retry on stale provider
  - **Vector search** (`vector_search`): pgvector ANN cosine similarity via `<=>` operator, capped at 50 candidates, includes `version` and `vector_score` per result
  - **Keyword search** (`keyword_search`): GIN full-text search with `ts_rank` scoring, capped at 50 candidates, includes `version` and `keyword_score` per result
  - **RRF fusion** (`rrf_fusion`): combines vector + keyword results using `SUM(1 / (k + rank))` with k=60, deduplicates by ID
  - **Score normalization** (`_normalize_rrf_scores`): maps RRF scores to [0,1] by dividing by max score
  - **Final scoring** (`compute_final_scores`): `0.4 * normalized_rrf + 0.3 * recency + 0.3 * trust_tier + 0.15 (if summary)`, sorts descending
  - **Token budget packing** (`pack_results`): `_CHARS_PER_TOKEN = 8` with content truncation and `truncated` flag
  - **Hybrid orchestrator** (`hybrid_search`): graceful degradation — if encoding fails, falls back to keyword-only with `degraded: true` flag
  - **Service integration** (`read_context` in `service.py`): routes queries through `hybrid_search()`, falls through to chronological when hybrid returns no results
  - **API updates:** `ReadContextUnitModel` now includes `version` field; `query` param has `max_length=500`; `scope` uses `Literal["onboarding", "task", "full"]`
  - Sub-queries run sequentially (asyncpg sessions are not concurrency-safe)
  - 187 total tests, zero regressions

- **Phase 2.4 — Redis Live Presence** (2026-07-25)
  - **New module:** `loom/services/coordination/presence.py` — agent heartbeat recording and presence querying:
    - `record_heartbeat()` — stores `project_id`, `status`, `task_id` in `presence:agent:{agent_id}` Redis hash with 60s TTL using pipelined `HSET` + `EXPIRE`
    - `get_active_agents()` — project-scoped agent list via `SCAN` iteration (not `KEYS`), pipelined `HGETALL`, returns `agent_id`/`project_id`/`status`/`task_id`
    - `get_agent_presence()` — single-agent presence lookup with `dict` or `None` response
    - All three functions accept `redis=None` and degrade gracefully (return `False`/`[]`/`None`)
    - Redis errors (`ConnectionError`, `TimeoutError`, `OSError`, `redis_exceptions.*`) caught and logged
  - **`AuthContext` extended** (`loom/api/auth.py`): `project_id` field added (default `None`) — enables endpoints to know which project an agent belongs to without a separate DB call
  - **New FastAPI dependency** (`loom/api/dependencies.py`): `get_redis` — reuses the existing module-level Redis singleton from `loom.services.retrieval.queue`; returns `None` on error for graceful degradation
  - **Event type schemas** (`loom/schemas/events.py`): `AgentEventType` literal type with 5 members (`agent_online`, `agent_heartbeat`, `agent_offline`, `agent_lock`, `agent_unlock`) and 5 payload type aliases — schema only, no WebSocket implementation
  - **Heartbeat endpoint** `POST /v1/agents/{agent_id}/heartbeat`:
    - Auth + `agent_id` match enforcement (403 `AGENT_ID_MISMATCH` on mismatch)
    - Request body: `status` (`"idle"|"working"|"blocked"`), optional `task_id`
    - Response: `{"status": "ok", "redis_available": true|false}`
    - Pydantic validation on `status` literal (422 on invalid value)
  - **Presence query endpoint** `GET /v1/projects/{project_id}/agents/presence`:
    - Cross-project access guard (403 `PROJECT_MISMATCH` if auth agent belongs to a different project)
    - Returns list of active agents with `agent_id`, `project_id`, `status`, `task_id`
    - Returns empty list when no agents have heartbeats or Redis is down
  - **23 new tests** (13 unit + 10 integration) covering:
    - All three service functions with Redis and `redis=None` degradation
    - Heartbeat API: auth mismatch, missing auth, invalid status, task_id storage, Redis-down resilience
    - Presence query: active agent retrieval, empty state, missing auth, cross-project access block
  - 234 total tests, zero regressions

- **Phase 2.5a — Agent Activity Sidebar + Conflict Badge** (2026-07-26)
  - **Agent Activity Sidebar** in the extension popup — collapsible panel showing live agents with status dots (online/idle/working/blocked/offline), task description, heartbeat time, and last write
  - **Conflict Badge** on the extension icon — red badge with pending conflict count, updated via `chrome.alarms`-based background polling every 60s
  - **Conflict list** in the activity panel — type, created time, and context unit ID for each pending conflict
  - **Background polling** via `chrome.alarms` (MV3-safe) — `LOOM_CONFLICT_POLL` alarm with periodInMinutes dedup check
  - **Popup-side polling** — agent presence every 5s, conflicts every 30s, relative time ticker every 1s; pauses when panel is hidden
  - **Storage layer** — `getCurrentProject()`, `setCurrentProject()`, `clearCurrentProject()` for cross-popup project persistence
  - **Message handlers** — `GET_AGENT_PRESENCE`, `GET_CONFLICTS`, `SET_CURRENT_PROJECT` in background service worker
  - **Security hardening** — `escapeHtml()` for all user-visible text, status value whitelist, CSP meta tag in popup, sender validation in background message handler, `escapeHtml` fix for `LOOM_LINKED` banner in content.js
  - **Code Review fixes** — HTML attribute injection patched, CSS class injection patched, polling stops on panel hide, conflict timestamps updated via DOM (no 1Hz full re-render), badge background color set once
  - **No backend changes** — all 234 backend tests unchanged
  - **6 files modified** — all in `extension/` (manifest.json, config.js, storage.js, background.js, popup.html, popup.js, content.js)

- **Phase 2.5b — Push-to-Loom from Chat + Project Dashboard** (2026-07-26)
  - **Push-to-Loom** — right-click context menu on any page → "Send to Loom as context" — writes selected text to the linked project via `POST /v1/projects/{id}/context` with `trust_tier: "user"`, `type: "decision"`, deterministic SHA-256 client UUID for idempotency
  - **Project Dashboard** — full-page SPA at `/v1/projects/{id}/dashboard` showing project overview, active agents (from presence endpoint), recent context feed (from chrono read), and pending conflicts — auth via URL fragment (`#token=xxx`) cleared after load
  - **Backend** — new `GET /v1/projects/{id}` endpoint (200/401/404), `source_url` field on write endpoint (forward-compat), dashboard HTML served via `FileResponse` at `/v1/projects/{id}/dashboard`
  - **Extension changes** — `contextMenus` permission, context menu creation in `onInstalled`, `contextMenus.onClicked` handler in background.js, "Open Dashboard" button in popup, `PUSH_TO_LOOM` config with text normalization and 100KB truncation
  - **4 new tests** for `GET /v1/projects/{id}` (success, no auth, not found, wrong agent)
  - **238 total tests**, zero regressions (234 + 4 new)
