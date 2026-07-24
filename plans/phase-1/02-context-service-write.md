---
title: "Phase 1.2 — Context Service: Write Path"
description: "REST endpoint POST /v1/projects/{id}/context that validates, appends to event log, inserts context unit + edges in a single transaction."
status: completed
dependencies: ["phase-1/01-db-schema.md"]
---

# Context Service: Write Path

## Description
Implement the write side of the Context Service. When an agent writes context, the service must: validate the payload, check for conflicts (via version), append an immutable event to the event_log, insert the context_unit row (with edges), and trigger async embedding — all within a single database transaction.

## Location
`services/context/service.py` — the core write function
`api/routes/context.py` — the REST endpoint handler

## API Specification

```
POST /v1/projects/{project_id}/context
Authorization: Bearer <agent-api-key>

Request Body:
{
    "client_uuid": "uuid-string",         // Client-generated, for idempotency
    "type": "message|decision|artifact_ref|task_result|summary",
    "trust_tier": "user|agent|external_tool",
    "content": "text content of the context unit",
    "parent_ids": ["uuid1", "uuid2"],     // IDs of parent context units
    "parent_relations": ["derived_from", "references"],
    "version": 1                          // Optimistic concurrency version
}

Response 201:
{
    "id": "uuid-string",
    "client_uuid": "uuid-string",
    "created_at": "2026-07-23T12:00:00Z",
    "version": 1
}

Response 409 (Conflict):
{
    "error": "CONFLICT",
    "message": "Version mismatch: expected version 2 but got 1",
    "current_version": 2,
    "pending_branch_id": "uuid"
}
```

## Implementation Requirements

### Transaction Flow
1. Begin transaction
2. Check idempotency: does `client_uuid` already exist? If yes, return existing record
3. Check version: if `version` < current version of parent, raise conflict
4. Insert into `context_units` table
5. Insert into `context_edges` for each parent
6. Append to `event_log` with event_type='write', payload containing the full context
7. Enqueue async embedding job (Redis list)
8. Commit transaction
9. Return the new context unit ID

### Validation Rules
- `project_id` must reference an existing project
- `agent_id` is derived from the auth token (not a client parameter)
- `type` must be a valid enum value
- `trust_tier` must be a valid enum value
- `content` must be non-empty and within size limits (max 100KB for v1)
- `parent_ids` must reference existing context units in the same project
- `version` must be >= 1

### Error Responses
```
400 — Validation error (missing field, invalid enum, content too large)
401 — Unauthorized (missing or invalid API key)
404 — Project not found
409 — Version conflict (concurrent write detected)
```

## File Targets
- `services/context/__init__.py`
- `services/context/service.py` — `write_context()` function
- `api/routes/context.py` — POST handler
- `api/middleware.py` — auth middleware (extract agent_id from token)

## Acceptance Criteria

- [ ] POST returns 201 with the new context unit ID
- [ ] POST with same `client_uuid` returns the same record (idempotent, no duplicate)
- [ ] POST with stale `version` returns 409 with conflict details
- [ ] Event log contains one `write` event per successful write
- [ ] Context edges are created for each parent_id
- [ ] Unauthorized requests return 401
- [ ] Invalid project returns 404

## TDD Instructions

**Before implementing:** Write tests for each validation rule and the main write path:

```python
@pytest.mark.asyncio
async def test_write_context_success(client, test_project, test_agent):
    resp = await client.post(f"/v1/projects/{test_project}/context", json={
        "client_uuid": str(uuid4()),
        "type": "message",
        "content": "Hello from agent",
        "version": 1
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data

@pytest.mark.asyncio
async def test_write_context_idempotent(client, test_project, test_agent):
    body = {"client_uuid": str(uuid4()), "type": "message", "content": "test", "version": 1}
    resp1 = await client.post(f"/v1/projects/{test_project}/context", json=body)
    resp2 = await client.post(f"/v1/projects/{test_project}/context", json=body)
    assert resp1.json()["id"] == resp2.json()["id"]

@pytest.mark.asyncio
async def test_write_context_version_conflict(client, test_project, test_agent):
    # Write once (version 1), then write again with version 1 — should conflict
    pass
```

## Dependencies
- Phase 1.1 (database schema must be applied)
