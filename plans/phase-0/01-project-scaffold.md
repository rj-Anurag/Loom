---
title: "Phase 0.1 — Project Scaffold"
description: "Create the repository skeleton: directory structure, README, LICENSE, .gitignore, and initial configuration files."
status: completed
framework: "FastAPI + SQLAlchemy async + asyncpg + Redis + Pydantic"
dependencies: []
---

# Project Scaffold

## Description
Initialize the Loom repository with a clean, opinionated directory structure and all the meta-files every project needs.

## Directory Structure
```
loom/                          # Main Python package
├── __init__.py
├── config.py                  # Pydantic Settings
├── db.py                      # SQLAlchemy async engine + session
├── api/                       # FastAPI context server (backing API for MCP tools & extension)
│   ├── __init__.py
│   ├── main.py                # FastAPI app, routers, middleware
│   └── routers/
│       ├── __init__.py
│       ├── context.py         # /v1/projects/{id}/context endpoints
│       └── agents.py          # /v1/agents endpoints
├── services/                  # Business logic (framework-agnostic)
│   ├── __init__.py
│   ├── context/
│   │   ├── __init__.py
│   │   └── service.py
│   ├── coordination/
│   │   ├── __init__.py
│   │   └── service.py
│   └── retrieval/
│       ├── __init__.py
│       ├── service.py
│       ├── search.py
│       └── summarizer.py
├── agents/                    # Agent runtimes
│   ├── __init__.py
│   ├── local/
│   │   ├── __init__.py
│   │   └── agent.py
│   └── cloud/
│       ├── __init__.py
│       └── agent.py
├── compliance/
│   └── __init__.py
├── infra/                     # Infrastructure configs
│   ├── docker-compose.yml
│   └── Dockerfile
├── tools/                     # Developer tooling
│   └── orchestrator/
│       ├── __init__.py
│       ├── cli.py
│       ├── core.py
│       ├── planner.py
│       ├── coder.py
│       ├── test_runner.py
│       ├── fixer.py
│       ├── reviewer.py
│       └── tests/
├── extension/                 # Browser extension (Chrome/Firefox)
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_project_meta.py
│   ├── unit/
│   ├── integration/
│   └── load/
├── scripts/
│   ├── migrate.sh
│   ├── seed.sh
│   └── health-check.sh
├── .github/
│   └── workflows/
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── pyproject.toml
└── loom-architecture.md
```

## Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| **Web framework** | FastAPI | Async-native, WebSocket support, Pydantic validation, auto OpenAPI docs |
| **ORM** | SQLAlchemy 2.0 async | Mature async ORM with pgvector support |
| **Database driver** | asyncpg | Fastest async PostgreSQL driver |
| **Database** | PostgreSQL 16 + pgvector | Vector embeddings + relational data in one DB |
| **Cache / Queue** | Redis 7 | Pub/sub for live events, queues for async jobs, locks for coordination |
| **Validation** | Pydantic v2 + pydantic-settings | Request validation + env config |
| **Testing** | pytest + pytest-asyncio + httpx | Async test support with ASGI transport |
| **Linting** | ruff | Fast Python linter |
| **Type checking** | mypy | Strict mode |
| **LLM** | Anthropic SDK | Agent LLM calls |
| **Server** | uvicorn | ASGI server for FastAPI |
| **Logging** | structlog | Structured JSON logging |

## Files to Create

1. **`loom/__init__.py`** — Package version
2. **`loom/config.py`** — `pydantic-settings` BaseSettings class
3. **`loom/db.py`** — SQLAlchemy async engine + session factory + Base
4. **`loom/api/__init__.py`** — Package init
5. **`loom/api/main.py`** — FastAPI app with CORS, router includes, health endpoint
6. **`loom/api/routers/__init__.py`** — Package init
7. **`loom/api/routers/context.py`** — GET/POST /v1/projects/{id}/context stubs
8. **`loom/api/routers/agents.py`** — POST heartbeat + register agent stubs
9. **`loom/services/__init__.py`** + all service sub-package inits
10. **`loom/agents/__init__.py`** + local/cloud inits
11. **`README.md`** — Project name, description, quick-start, structure diagram
12. **`LICENSE`** — MIT license
13. **`.gitignore`** — Python, Node, Docker, IDE, OS files
14. **`pyproject.toml`** — Project metadata, deps (fastapi, sqlalchemy, asyncpg, redis, etc.), tool configs
15. **`.env.example`** — Documented env vars with placeholder values
16. **`tests/conftest.py`** — Pytest fixtures (AsyncClient with ASGITransport, event_loop)
17. **`tests/test_project_meta.py`** — Import and config validation tests

## Acceptance Criteria

- [ ] `python -c "import loom; print(loom.__version__)"` works
- [ ] `python -c "from loom.config import Settings; s=Settings(); print(s.api_host)"` works
- [ ] `python -c "from loom.api.main import app; print(app.title)"` works
- [ ] `pytest tests/` discovers and runs (2 tests: import + toml validation)
- [ ] `ruff check .` passes
- [ ] `mypy .` passes
- [ ] `pip install -e ".[dev]"` installs the package in editable mode
- [ ] `.gitignore` covers Python, Node, Docker, macOS, IDE artifacts, and state.json

## TDD Instructions

**Before implementing:** Write a test that the package imports correctly:
```python
# tests/test_imports.py
def test_package_imports():
    import loom  # noqa: F401
    assert True
```

Write a test that `pyproject.toml` is valid TOML:
```python
# tests/test_project_meta.py
import tomllib
from pathlib import Path

def test_pyproject_is_valid_toml():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "project" in data
```

These tests should pass after the scaffold is complete.

## Dependencies
None.
