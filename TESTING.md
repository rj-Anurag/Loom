# Loom — Phase 1 Testing Guide

Comprehensive walkthrough for testing all Phase 1 functionality: context CRUD,
coordination, embeddings, the local agent, the browser extension backend, and
the concurrent-merge load test.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Start Infrastructure](#2-start-infrastructure)
3. [Apply Database Migrations](#3-apply-database-migrations)
4. [Run the Automated Test Suite](#4-run-the-automated-test-suite)
5. [Manual API Testing with Curl](#5-manual-api-testing-with-curl)
6. [Test Coordination & Auto-Merge](#6-test-coordination--auto-merge)
7. [Test the Embedding Pipeline](#7-test-the-embedding-pipeline)
8. [Run the Load Test](#8-run-the-load-test)
9. [Test the Local Agent](#9-test-the-local-agent)
10. [Test the Browser Extension](#10-test-the-browser-extension)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | Tested with 3.11 |
| Docker | 24+ | For PostgreSQL + pgvector + Redis |
| Node.js | 18+ | Only needed to lint extension JS files |
| Chrome | Latest | To load the browser extension |

### Python Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install httpx pytest pytest-asyncio pytest-asyncio httpx pytest-asyncio
```

> The `[dev]` extra installs pytest and related test tools.
> If it doesn't exist, run: `pip install pytest pytest-asyncio httpx pytest-asyncio`

### Environment

Copy `.env.example` to `.env` (already done if you've been following along):

```bash
cp .env.example .env
```

The `.env` file should contain:

```
DATABASE_URL=postgresql+asyncpg://loom:loom@localhost:5432/loom
REDIS_URL=redis://localhost:6379/0
API_HOST=0.0.0.0
API_PORT=8000
ENVIRONMENT=development
EMBEDDING_PROVIDER=stub
GROQ_API_KEY=gsk_...  # optional, only needed for local agent LLM calls
```

---

## 2. Start Infrastructure

Start PostgreSQL (with pgvector) and Redis via Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up -d
```

Verify both are healthy:

```bash
docker compose -f infra/docker-compose.yml ps
```

Expected output:

```
NAME            IMAGE                           STATUS
loom-postgres   pgvector/pgvector:pg16          Up (healthy)
loom-redis      redis:7-alpine                  Up (healthy)
```

---

## 3. Apply Database Migrations

The migrations are SQL files in `loom/services/context/migrations/`. Apply them:

```bash
./scripts/migrate.sh up
```

This creates all tables: `projects`, `agents`, `context_units`, `context_edges`,
`event_log`, `pending_branches`, `chat_links`, plus indexes and the `_migrations`
tracking table.

Verify migrations were applied:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -c "SELECT filename, applied_at FROM _migrations ORDER BY id;"
```

Expected output (8 migrations):

```
           filename           |          applied_at
------------------------------+-------------------------------
 001_create_projects.sql      | 2026-07-24 ...
 002_create_agents.sql        | 2026-07-24 ...
 003_create_context_units.sql | 2026-07-24 ...
 004_create_context_edges.sql | 2026-07-24 ...
 005_create_event_log.sql     | 2026-07-24 ...
 006_create_pending_branches.sql | 2026-07-24 ...
 007_create_indexes.sql       | 2026-07-24 ...
 008_chat_links.sql           | 2026-07-24 ...
```

If any are missing, run: `./scripts/migrate.sh up` again to apply pending ones.

### Seed Test Data (Optional)

```bash
./scripts/seed.sh
```

This creates a "Development Test Project" if one doesn't exist.

---

## 4. Run the Automated Test Suite

### All Tests

```bash
python -m pytest tests/ -v --tb=short
```

Expected: **111 passed** (or more if new tests were added).

### Test Breakdown by Group

| Test File | What It Tests | Count |
|---|---|---|
| `tests/integration/test_db_schema.py` | All 7 DB tables exist, columns, constraints, FKs | 17 |
| `tests/integration/test_context_write.py` | Writing context units, idempotency, version conflicts, event log, validation | 11 |
| `tests/integration/test_context_read.py` | Reading context, full-text search, budget packing, scope, ranking | 11 |
| `tests/integration/test_event_log.py` | Enriched payload, content hash, chronological order, rebuild | 5 |
| `tests/integration/test_versioning.py` | PendingBranch creation, structured 409, multiple conflicts | 4 |
| `tests/integration/test_trust_tier.py` | Agent kind → allowed trust tiers, 403 on denied | 6 |
| `tests/integration/test_coordination.py` | Entity extraction, overlap detection, auto-merge, conflict list/resolve | 7 |
| `tests/integration/test_mcp_tools.py` | 3 MCP tools (read, write, summary) via ToolRegistry | 10 |
| `tests/integration/test_embedding_pipeline.py` | StubProvider, Redis queue, worker, DLQ, recovery | 17 |
| `tests/integration/test_local_agent.py` | LoomClient, GroqLLM, LocalAgent loop | 10 |
| `tests/integration/test_projects.py` | List projects, create project, link chat | 10 |
| `tests/load/test_concurrent_merges.py` | 3-agent concurrent write load test | 1 |
| `tests/test_project_meta.py` | Package imports, pyproject.toml validity | 2 |

### Run a Single Test File

```bash
python -m pytest tests/integration/test_context_write.py -v --tb=short
```

### Run a Single Test

```bash
python -m pytest tests/integration/test_context_write.py::test_write_context_success -v
```

### Run with More Output

```bash
python -m pytest tests/ -v --tb=long --no-header -s
```

---

## 5. Manual API Testing with Curl

Start the Loom server:

```bash
uvicorn loom.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5.1 Health Check

```bash
curl -s http://localhost:8000/health
```

Expected:
```json
{"status":"ok"}
```

### 5.2 Create a Project (with Browser Agent)

```bash
# First, you need an agent token. Create a project with a local agent:
curl -s -X POST http://localhost:8000/v1/projects \
  -H "Authorization: Bearer $(curl -s http://localhost:8000/v1/projects | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Test Project"}'
```

But you need an auth token first. Let's bootstrap:

#### Step 1: Create an agent directly in the database

```bash
# Get a project UUID first (or create one via SQL)
PROJECT_ID=$(docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -t -c "INSERT INTO projects (name) VALUES ('Manual Test') RETURNING id;" | tr -d ' ')

# Create a local-kind agent for that project
AGENT_ID=$(docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -t -c "INSERT INTO agents (project_id, kind) VALUES ('$PROJECT_ID', 'local') RETURNING id;" | tr -d ' ')

echo "Project ID: $PROJECT_ID"
echo "Agent ID (use as Bearer token): $AGENT_ID"
```

#### Step 2: Export the token

```bash
export TOKEN=$AGENT_ID
export PID=$PROJECT_ID
```

### 5.3 List Projects

```bash
curl -s http://localhost:8000/v1/projects \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.4 Write Context

```bash
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
    "type": "decision",
    "content": "We decided to use bcrypt for password hashing",
    "version": 1
  }' | python3 -m json.tool
```

Expected response (201 Created):
```json
{
  "id": "...",
  "client_uuid": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
  "created_at": "2026-07-24T...",
  "version": 1
}
```

### 5.5 Idempotent Write (Same client_uuid)

Send the exact same request again:

```bash
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
    "type": "decision",
    "content": "We decided to use bcrypt for password hashing",
    "version": 1
  }' | python3 -m json.tool
```

Expected: **200 OK** (not 201) — returns the same record. No duplicate created.

### 5.6 Read Context

```bash
curl -s "http://localhost:8000/v1/projects/$PID/context?query=bcrypt&budget=4096" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected:
```json
{
  "units": [
    {
      "id": "...",
      "type": "decision",
      "trust_tier": "agent",
      "content": "We decided to use bcrypt for password hashing",
      "created_at": "...",
      "agent_id": "...",
      "parent_ids": [],
      "relevance_score": 0.8
    }
  ],
  "total_tokens": 6,
  "budget_used": 6,
  "truncated": false
}
```

### 5.7 Write with Parent References

```bash
# First write a parent
PARENT=$(curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb",
    "type": "decision",
    "content": "We need a Redis cache layer",
    "version": 1
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Write a child referencing the parent (version must be parent.version + 1 = 2)
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_uuid\": \"cccccccc-cccc-4ccc-cccc-cccccccccccc\",
    \"type\": \"task_result\",
    \"content\": \"Implemented Redis in src/cache/redis_client.py\",
    \"version\": 2,
    \"parent_ids\": [\"$PARENT\"]
  }" | python3 -m json.tool
```

### 5.8 Version Conflict Test

```bash
# Try to write another child with stale version 1 (parent is version 1)
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_uuid\": \"dddddddd-dddd-4ddd-dddd-dddddddddddd\",
    \"type\": \"task_result\",
    \"content\": \"Different Redis implementation\",
    \"version\": 1,
    \"parent_ids\": [\"$PARENT\"]
  }" | python3 -m json.tool
```

Expected: **409 Conflict** with version conflict details.

### 5.9 Link a Chat URL to the Project

```bash
curl -s -X POST "http://localhost:8000/v1/projects/$PID/link/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_url": "https://claude.ai/chat/manual-test-123",
    "title": "Manual API Test Chat",
    "platform": "claude.ai"
  }' | python3 -m json.tool
```

Expected:
```json
{
  "id": "...",
  "project_id": "<PID>",
  "chat_url": "https://claude.ai/chat/manual-test-123",
  "title": "Manual API Test Chat",
  "platform": "claude.ai",
  "linked_at": "2026-07-24T..."
}
```

### 5.10 Create a Project via API

```bash
curl -s -X POST http://localhost:8000/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Browser Extension Project"}' | python3 -m json.tool
```

Note the `agent_id` and `api_key` in the response — these are the credentials
the browser extension would use.

### 5.11 Trust Tier Enforcement

The `local`-kind agent cannot write at `user` trust tier:

```bash
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "eeeeeeee-eeee-4eee-eeee-eeeeeeeeeeee",
    "type": "message",
    "content": "Human message",
    "version": 1,
    "trust_tier": "user"
  }' | python3 -m json.tool
```

Expected: **403 Forbidden** — a local agent cannot impersonate a human.

---

## 6. Test Coordination & Auto-Merge

This tests the concurrent-merge logic: two agents write to the same parent
simultaneously. Non-overlapping content → auto-merges. Overlapping → conflict.

### 6.1 Non-Overlapping Auto-Merge

```bash
# 1. Write a parent
PARENT=$(curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "ffffffff-ffff-4fff-ffff-ffffffffffff",
    "type": "decision",
    "content": "Decision: implement caching layer",
    "version": 1
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Write child C1 with correct version 2
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_uuid\": \"11111111-1111-4111-1111-111111111111\",
    \"type\": \"task_result\",
    \"content\": \"Built Redis cache in src/cache/redis_client.py\",
    \"parent_ids\": [\"$PARENT\"],
    \"version\": 2
  }" > /dev/null

# 3. Write child C2 with stale version 1 (auto-merge should kick in)
#    Content must NOT overlap with C1 (different file paths)
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_uuid\": \"22222222-2222-4222-2222-222222222222\",
    \"type\": \"task_result\",
    \"content\": \"Set up PostgreSQL in src/db/postgres_conn.py\",
    \"parent_ids\": [\"$PARENT\"],
    \"version\": 1
  }" | python3 -m json.tool
```

Expected: **201 Created** (not 409) — auto-merge adjusted the version.

### 6.2 Overlapping Conflict

```bash
# 4. Write another child with overlapping content (same file path)
#    This should create a PendingBranch
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_uuid\": \"33333333-3333-4333-3333-333333333333\",
    \"type\": \"task_result\",
    \"content\": \"Using Redis for session store in src/cache/redis_client.py\",
    \"parent_ids\": [\"$PARENT\"],
    \"version\": 1
  }" | python3 -m json.tool
```

Expected: **409 Conflict** with `pending_branch_id`.

### 6.3 List Conflicts

```bash
curl -s "http://localhost:8000/v1/projects/$PID/conflicts" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 6.4 Resolve a Conflict

```bash
# Replace BRANCH_ID with the pending_branch_id from step 6.2
curl -s -X POST "http://localhost:8000/v1/projects/$PID/conflicts/BRANCH_ID/resolve" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resolution": "resolved"}' | python3 -m json.tool
```

---

## 7. Test the Embedding Pipeline

The embedding pipeline consists of:
- A **queue** (Redis) — jobs are enqueued after each context write
- A **worker** (`embedding_worker.py`) — processes jobs asynchronously
- **Providers** — pluggable embedding implementations (StubProvider for testing)

### 7.1 Verify Queue After Writing

Each context write should enqueue an embedding job. Verify with Redis:

```bash
docker compose -f infra/docker-compose.yml exec -T redis \
  redis-cli LLEN embedding:queue
```

Should return > 0 if any context units were written.

### 7.2 Run the Embedding Worker

```bash
./scripts/run-embedding-worker.sh
```

This starts the worker in the foreground. It processes pending jobs and exits
when the queue is empty. You should see log lines like:

```
Processing job <uuid> for unit <uuid>...
Embedding stored for unit <uuid>
```

### 7.3 Check DLQ (Dead Letter Queue)

If a job fails after 3 retries, it moves to the DLQ:

```bash
docker compose -f infra/docker-compose.yml exec -T redis \
  redis-cli LLEN embedding:dlq
```

---

## 8. Run the Load Test

This simulates 3 agents writing 45 context units concurrently, measuring
latency and conflict/auto-merge accuracy.

### Quick Run

```bash
python -m pytest tests/load/test_concurrent_merges.py -v --tb=short -m load_test \
  -o "markers=load_test: concurrent-merge load test"
```

### With the Shell Script

```bash
./scripts/run-load-tests.sh
```

### Reading the Report

After the test, a JSON report is written to `tests/load/last-report.json`:

```bash
python3 -m json.tool tests/load/last-report.json
```

Key metrics:

| Metric | Target | Meaning |
|---|---|---|
| `latency_ms.p99` | < 500ms | 99th percentile write latency |
| `conflicts.flagged` | ≥ 10 | Overlapping writes correctly rejected |
| `conflicts.false_positives` | 0 | Non-overlapping writes incorrectly rejected |
| `data_loss` | false | All non-conflicting writes persisted |
| `all_writes_accounted` | true | DB count matches successful writes |

### What the Load Test Does

1. Creates 3 agents (auth, schema, api) for one shared project
2. **Phase 1** — 5 independent writes per agent (no shared parent)
3. **Phase 2** — 5 writes per agent deriving from the same parent, using
   non-overlapping content (tests auto-merge)
4. **Phase 3** — 5 writes per agent deriving from the same parent, using
   overlapping content with stale versions (tests conflict detection)

---

## 9. Test the Local Agent

The local agent is a Python CLI tool that demonstrates the full
read → LLM (Groq) → write loop.

### Prerequisites

A valid `GROQ_API_KEY` in `.env`. Get one free at https://console.groq.com/keys.

### 9.1 Seed a Project with Context

```bash
# The agent reads context from a project.
# First create a project + agent:
PID=$(docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -t -c "INSERT INTO projects (name) VALUES ('Agent Test') RETURNING id;" | tr -d ' ')

AID=$(docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -t -c "INSERT INTO agents (project_id, kind) VALUES ('$PID', 'local') RETURNING id;" | tr -d ' ')

echo "Project ID: $PID"
echo "Agent Token: $AID"

# Write some seed context about the project
curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $AID" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "seed-001-0000-0000-0000-000000000001",
    "type": "decision",
    "content": "We chose PostgreSQL for data storage and Redis for caching",
    "version": 1
  }' > /dev/null

curl -s -X POST "http://localhost:8000/v1/projects/$PID/context" \
  -H "Authorization: Bearer $AID" \
  -H "Content-Type: application/json" \
  -d '{
    "client_uuid": "seed-001-0000-0000-0000-000000000002",
    "type": "decision",
    "content": "Authentication uses bcrypt for password hashing with JWT for sessions",
    "version": 1
  }' > /dev/null
```

### 9.2 Run the Agent (Dry Run)

```bash
python -m agents.local.agent --task "Summarize the tech stack decisions" \
  --project $PID --dry-run -v
```

Expected output: reads context, builds a prompt, prints it but skips the LLM call.

### 9.3 Run the Agent (Real LLM Call)

```bash
python -m agents.local.agent --task "What technology decisions have been made?" \
  --project $PID -v
```

This calls the Groq LLM with the retrieved context, then writes the LLM's
response back to Loom as a new context unit.

### 9.4 Verify the Agent's Write

```bash
curl -s "http://localhost:8000/v1/projects/$PID/context?query=technology&budget=4096" \
  -H "Authorization: Bearer $AID" | python3 -m json.tool
```

You should see the agent's response in the results.

---

## 10. Test the Browser Extension

### 10.1 Load the Extension in Chrome

1. Open Chrome and navigate to `chrome://extensions`
2. Enable **Developer mode** (toggle top-right)
3. Click **Load unpacked**
4. Select the `extension/` directory in this project
5. The "Loom — Context Bridge" extension should appear

### 10.2 Configure the Extension

By default, the extension connects to `http://localhost:8000`.
To change this, edit `extension/config.js`:

```js
LOOM_SERVER_URL: 'http://localhost:8000',
```

### 10.3 Verify Backend API Works for the Extension

First, start the Loom server:

```bash
uvicorn loom.api.main:app --host 0.0.0.0 --port 8000
```

Then test the extension's API calls manually:

```bash
# 1. Create a project (returns browser agent credentials)
curl -s -X POST http://localhost:8000/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Extension Test Project"}' | python3 -m json.tool
```

### 10.4 Test the Content Script

The content script (`extension/content.js`) activates on `https://claude.ai/*`.

1. Start the Loom server: `uvicorn loom.api.main:app --host 0.0.0.0 --port 8000`
2. Open `https://claude.ai/` in Chrome (with the extension loaded)
3. Open a chat conversation
4. The content script injects a banner at the top of the page:
   > **Loom** — Link this chat to a project?  [Link] [Not now]
5. Click **Link** to open the popup

> **Note**: The extension requires `https://claude.ai/` to be accessible.
> If you're not a Claude.ai user, the content script won't have a page to
> inject into. The backend API still works independently.

### 10.5 Test the Popup

1. Click the Loom extension icon in the Chrome toolbar
2. If you're on a Claude.ai chat page, the popup shows one of:
   - **Linked** status (if the chat URL is already linked to a project)
   - **Link UI** with a project selector dropdown and "Create new project"
3. Select a project and click **Link Chat**

### 10.6 Test Message Sync

After linking:
1. Type a message in Claude.ai
2. The content script detects the new DOM element and sends it to the
   background worker
3. The background worker calls `POST /v1/projects/{id}/context` with
   the message content at `trust_tier: "user"`
4. Verify the synced message is readable:

```bash
curl -s "http://localhost:8000/v1/projects/$PID/context?query=...&budget=4096" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## 11. Troubleshooting

### Tests fail with "relation does not exist"

Migrations haven't been applied. Run:

```bash
./scripts/migrate.sh up
```

### Docker container won't start

Port conflict (5432 or 6379 already in use):

```bash
# Check what's using the port
lsof -i :5432
lsof -i :6379

# Stop the conflicting service or change the port in docker-compose.yml
```

### "Cannot connect to database"

Ensure Docker is running and the containers are healthy:

```bash
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs postgres
```

### Load test fails with "Foreign key violation"

The database has stale data. Clean it:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U loom -d loom -c "
    DELETE FROM context_edges;
    DELETE FROM event_log;
    DELETE FROM pending_branches;
    DELETE FROM context_units;
    DELETE FROM agents;
    DELETE FROM projects;
    DELETE FROM chat_links;
  "
```

### Extension shows "Could not connect to Loom"

Make sure the Loom server is running on port 8000:

```bash
curl http://localhost:8000/health
```

### Pytest warnings about "load_test" marker

The marker is registered in `pyproject.toml`. Make sure you're running
pytest from the project root so it picks up the config.

### Agent says "No project_id provided"

Either pass `--project <uuid>` or set the `LOOM_PROJECT_ID` environment
variable:

```bash
export LOOM_PROJECT_ID=<your-project-uuid>
```

---

## API Endpoint Reference

| Method | Path | Description | Phase |
|---|---|---|---|
| `GET` | `/health` | Health check | 1.2 |
| `GET` | `/v1/projects` | List all projects | 1.11 |
| `POST` | `/v1/projects` | Create project + browser agent | 1.11 |
| `GET` | `/v1/projects/{id}/context` | Read context (with search) | 1.3 |
| `POST` | `/v1/projects/{id}/context` | Write context unit | 1.2 |
| `POST` | `/v1/projects/{id}/link/chat` | Link chat URL to project | 1.11 |
| `GET` | `/v1/projects/{id}/conflicts` | List pending conflicts | 1.8 |
| `POST` | `/v1/projects/{id}/conflicts/{bid}/resolve` | Resolve a conflict | 1.8 |
| `POST` | `/v1/agents/{id}/heartbeat` | Agent heartbeat | 1.2 |
| `POST` | `/v1/projects/{id}/agents` | Register agent | 1.2 |

---

## End-to-End Smoke Test

Once everything is set up, run this sequence to verify the full pipeline:

```bash
# 1. Health check
curl -s http://localhost:8000/health

# 2. Create project
curl -s -X POST http://localhost:8000/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test"}'

# 3. Write context
# 4. Read context
# 5. Link a chat
# 6. Run the load test
# 7. Run the full test suite
./scripts/run-load-tests.sh
python -m pytest tests/ -v --tb=short
```

All should pass.
