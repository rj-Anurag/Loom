# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Loom Is

Loom is a "context layer for the agentic era": it syncs browser AI chats (via a Chrome extension on claude.ai) and CLI agent sessions into a shared, append-only context store, retrievable via the `loom` CLI, MCP tools, REST API, or a web dashboard. Design source of truth: `loom-architecture.md`. Phased roadmap: `plans/`. `CHANGELOG.md` is actively maintained per phase.

## Commands

```bash
# Setup
pip install -e ".[dev]"                            # or uv
cp .env.example .env

# Infrastructure (required for the server and integration tests)
docker compose -f infra/docker-compose.yml up -d   # Postgres 16 + pgvector, Redis 7
./scripts/migrate.sh up                            # applies raw SQL migrations via docker compose exec

# Run
uvicorn loom.api.main:app                          # or: loom serve
loom mcp                                           # MCP stdio server
scripts/run-embedding-worker.sh                    # Redis-queue embedding worker
scripts/run-summarizer.sh                          # summarization worker

# Lint / typecheck (same as CI)
ruff check .
mypy .

# Test — integration tests hit real Postgres/Redis; infra must be up + migrated
pytest                                             # all tests (load tests excluded by marker)
pytest tests/integration/test_context_write.py     # single file
pytest tests/integration/test_context_write.py::test_name -v   # single test
./scripts/run-load-tests.sh                        # load tests (pytest -m load_test)
```

Migrations are numbered raw SQL files in `loom/services/context/migrations/`, applied by `scripts/migrate.sh` (tracked in a `_migrations` table). Alembic is a dependency but is NOT used.

pytest runs with `asyncio_mode = "auto"` and a session-scoped event loop; Redis tests use DB 1.

## Architecture

Modular monolith centered on a FastAPI server (`loom/api/main.py`, REST under `/v1` + WebSocket `/v1/projects/{id}/events`). Everything else is a client of it:

- `loom/cli/main.py` — `loom` console script (context, write, init, projects, mcp, serve)
- `loom/mcp/server.py` — FastMCP stdio server exposing read_context/write_context to Claude Code/opencode; proxies to REST
- `extension/` — Chrome MV3 extension (vanilla JS, no bundler): `content.js` captures claude.ai messages, `background.js` syncs them to `POST /v1/projects/{id}/context`
- `loom/web/dashboard.html` — single-file dashboard served at `GET /v1/projects/{id}/dashboard`; WS with polling fallback; auth token via `#token=` fragment
- `agents/local/`, `agents/demo/` — agent runtimes (HTTP clients of the API); multi-agent demo via `scripts/demo-multi-agent.sh`
- Workers consume Redis queues (`BRPOPLPUSH` + DLQ pattern in `loom/services/retrieval/`)

Services live in `loom/services/`: `context` (write/read paths + SQL migrations), `coordination` (branches, Redis locks, merge, presence, tasks), `retrieval` (embeddings, hybrid search, summarizer), `events`, `extension`, `links`, `projects`.

### Core invariants and design decisions

- **Append-only event log**: `event_log` mutations are blocked by Postgres triggers; `context_units`/`context_edges` are projections rebuildable from the log (`rebuild_projections()` in `loom/services/context/service.py`). "Context is never lost."
- **Idempotent writes**: `context_units.client_uuid` is UNIQUE; clients derive it deterministically (extension: SHA-256 of chatUrl + content). Replays return the existing row with 200 instead of 201.
- **Version conflict → branch → auto-merge** (`service.py` + `loom/services/coordination/merge.py`): a stale write with non-overlapping entities (file paths, def/class names, imports extracted by regex) is auto-merged with a `summary` merge unit and `merged_from` edges; overlapping writes get a 409 + `pending_branches` row.
- **Trust tiers**: `local`/`cloud` agents cannot write at `user` tier (`_ALLOWED_TRUST_TIERS` in `service.py`); trust tier also weights retrieval ranking.
- **Hybrid retrieval**: pgvector ANN + Postgres GIN full-text fused via Reciprocal Rank Fusion, with token-budget packing (`loom/services/retrieval/search.py`); degrades gracefully to keyword-only if the embedding provider fails.
- **Auth is MVP-grade**: agent UUID as Bearer token (`loom/api/auth.py`).
- **DB sessions use NullPool with lazy engine init** (`loom/db.py`) — deliberate workaround for test-client task-scoped connection issues; don't "optimize" it back to a pool without reading the module docstring.
- **Pluggable providers** via env: `EMBEDDING_PROVIDER` (stub | openai | sentence_transformers), `SUMMARIZATION_PROVIDER` (stub | groq) — `loom/services/retrieval/providers.py`.

## Workflow Rules (from AGENTS.md)

- TDD: write failing tests first, then implement; commit only after all tests pass.
- Commit format: `type: description` (feat, fix, refactor, docs, ...). Focused, atomic commits — split unrelated concerns.
- Work lands directly on `main` (no branching strategy). Never push without explicit user approval. Don't amend committed changes — create fresh commits.
- Update `CHANGELOG.md` for meaningful changes.
