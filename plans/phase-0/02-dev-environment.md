---
title: "Phase 0.2 — Development Environment"
description: "Docker Compose configuration for Postgres (with pgvector) and Redis. Environment variable templates and health-check scripts."
status: completed
framework: "FastAPI + SQLAlchemy async + asyncpg + Redis"
dependencies: ["phase-0/01-project-scaffold.md"]
---

# Development Environment

## Description
Set up the local development stack so any developer can run `docker-compose up` and get a working Postgres+pgvector + Redis environment with health checks and seed data.

## Deliverables

### 1. Docker Compose (`infra/docker-compose.yml`)

Services:
- **postgres**: Postgres 16 with pgvector extension pre-installed
  - Port 5432
  - Volume for data persistence
  - Health check: `pg_isready`
  - Preloaded SQL for the pgvector extension
- **redis**: Redis 7+
  - Port 6379
  - Health check: `redis-cli ping`

### 2. Environment Template (`.env.example`)

```
# Postgres
DATABASE_URL=postgresql://loom:loom@localhost:5432/loom
POSTGRES_USER=loom
POSTGRES_PASSWORD=loom
POSTGRES_DB=loom

# Redis
REDIS_URL=redis://localhost:6379/0

# API
API_PORT=8000
API_HOST=0.0.0.0

# Agent
AGENT_API_KEY=dev-agent-key-change-in-production
```

### 3. Health Check Script (`scripts/health-check.sh`)

A bash script that:
- Checks Postgres is accepting connections
- Checks Redis is responding
- Exits 0 if all healthy, 1 otherwise

### 4. Seed Script (`scripts/seed.sh`)

A bash script that:
- Creates the `pgvector` extension
- Creates a test project for development
- Inserts a few sample Context Units for manual testing

## Acceptance Criteria

- [ ] `docker-compose up` starts both services and both report healthy
- [ ] `psql -h localhost -U loom -d loom -c "SELECT 1"` works
- [ ] `redis-cli ping` returns `PONG`
- [ ] `pgvector` extension is installable: `CREATE EXTENSION vector;` succeeds
- [ ] `source .env.example && scripts/health-check.sh` exits 0
- [ ] All config values are documented in `.env.example` (no magic numbers)
- [ ] Containers restart gracefully on crash (`restart: unless-stopped`)

## TDD Instructions

**Before implementing:** Write a test that validates the docker-compose file is valid YAML:
```python
# tests/test_infra.py
import yaml
from pathlib import Path

def test_docker_compose_is_valid():
    with open("infra/docker-compose.yml") as f:
        config = yaml.safe_load(f)
    assert "services" in config
    assert "postgres" in config["services"]
    assert "redis" in config["services"]
```

Write a test that the env template has all required variables:
```python
def test_env_example_has_required_vars():
    from dotenv import dotenv_values
    config = dotenv_values(".env.example")
    assert config["DATABASE_URL"] is not None
    assert config["REDIS_URL"] is not None
```

## Dependencies
- Phase 0.1 (project scaffold must exist first)
