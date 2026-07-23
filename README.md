# Loom

A multi-agent collaboration platform where AI agents (local, cloud, browser-chat) share a persistent, append-only context layer. **Context is never lost, only compressed or deferred.**

## Tech Stack

| Component | Choice |
|---|---|
| Web framework | **FastAPI** (async) |
| ORM | **SQLAlchemy 2.0** async |
| Database | **PostgreSQL 16 + pgvector** |
| Cache / Queue | **Redis 7** |
| Validation | **Pydantic v2** |
| Server | **uvicorn** |
| Testing | **pytest + httpx** (ASGI) |
| Linting | **ruff** |
| Type checking | **mypy** (strict) |
| Logging | **structlog** |

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d
./scripts/migrate.sh up
./scripts/seed.sh
pytest
uvicorn loom.api.main:app --reload
```

## Architecture

Loom is a modular monolith with an event-driven core:

- **API Gateway** — FastAPI app, auth, routing, WebSocket for live updates
- **Context Service** — Read/write context units, append-only event log
- **Coordination Service** — Branch/merge for concurrent agent writes
- **Retrieval Service** — Embedding generation, hybrid search, summarization
- **Agent Services** — Local, cloud, and browser agent runtimes

See [loom-architecture.md](loom-architecture.md) for the full design, and [plans/](plans/) for the implementation roadmap.

## Project Structure

```
loom/
├── loom/                # Main Python package
│   ├── api/             # FastAPI app & routers
│   ├── services/        # Business logic
│   └── agents/          # Agent runtimes
├── web/                 # Browser chat UI
├── infra/               # Docker, K8s configs
├── tools/               # Orchestrator CLI
├── tests/               # Test suite
├── scripts/             # Utility scripts
├── plans/               # Implementation plans
├── .github/workflows/   # CI/CD
├── pyproject.toml       # Project config
└── loom-architecture.md # Architecture doc
```

## License

MIT
