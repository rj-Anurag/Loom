---
title: "Phase 1.6 — Idempotency & Versioning"
description: "Client-generated UUID deduplication and optimistic concurrency version checks for all context writes."
status: completed
dependencies: ["phase-1/02-context-service-write.md"]
---

# Idempotency & Versioning

## Description
Implement two critical safety guarantees: (1) idempotent writes via client-generated UUIDs, so retries never create duplicates, and (2) optimistic concurrency via version checks, so concurrent writes to the same context are detected rather than silently overwritten.

## Idempotency

### Client UUID Generation
Every `write_context` call must include a `client_uuid`. The client (agent) generates this UUID before sending the request.

### Server-Side Deduplication
When the server receives a write request:
1. Check if `client_uuid` already exists in `context_units`
2. If yes: return the existing record (201 with existing ID — idempotent success)
3. If no: proceed with the write

This means retries are always safe — the agent can retry a failed write without worrying about creating a duplicate.

### UUID Generation Strategy
For MCP tool calls, the `client_uuid` is generated using `uuid.uuid4()` before making the HTTP request. If the request fails (network error, timeout, 5xx), the agent retries with the same `client_uuid`.

## Optimistic Concurrency

### Version Field
Every `context_units` row has a `version` integer field, starting at 1 and incremented on every update.

However, in Loom's append-only model, context units are NOT updated — new units are created with `supersedes` edges. The version check applies to the **parent units**:

### Write-Time Version Check

```
Agent A writes context_unit_1 (version=1)
Agent B writes context_unit_2 (version=1) — parent is context_unit_1

Both say: "I derived from context_unit_1 at version=1"
Both pass — they're non-overlapping children of the same parent.
```

But if the system has a `version` on the parent, and a write claims to be based on an older version:

```
1. Agent X writes unit A (version=1)
2. Agent Y writes unit B that supersedes A (version=2)
3. Agent Z writes unit C that supersedes A, but specifies version=1
   → CONFLICT! Z didn't see B's supersede.
```

### Conflict Detection Logic

```python
async def check_version_conflict(conn, parent_ids, claimed_version):
    for parent_id in parent_ids:
        current = await conn.fetchval(
            "SELECT version FROM context_units WHERE id = $1",
            parent_id
        )
        if current and current != claimed_version:
            return Conflict(
                parent_id=parent_id,
                claimed_version=claimed_version,
                actual_version=current
            )
    return None
```

## File Targets
- `services/context/service.py` — add idempotency check and version conflict check to `write_context()`
- `tests/integration/test_idempotency.py` — integration tests
- `tests/integration/test_versioning.py` — integration tests

## Acceptance Criteria

- [ ] Same `client_uuid` sent twice returns the same context_unit ID (no duplicate)
- [ ] Different `client_uuid` with same content creates two separate units
- [ ] Write with stale parent version returns 409 conflict
- [ ] Write with correct parent version succeeds
- [ ] Conflict response includes current version and a pending_branch_id
- [ ] Idempotency works even if the first write was a partial success (e.g., DB commit succeeded but HTTP response was lost)

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_idempotent_write_returns_same_id(client, test_project):
    body = {"client_uuid": str(uuid4()), "type": "message", "content": "test", "version": 1}
    r1 = await client.post(f"/v1/projects/{test_project}/context", json=body)
    r2 = await client.post(f"/v1/projects/{test_project}/context", json=body)
    assert r1.json()["id"] == r2.json()["id"]

@pytest.mark.asyncio
async def test_version_conflict_detected(client, test_project):
    # Write unit A (version 1)
    a = await client.post(...)
    # Write unit B that supersedes A (becomes version 2)
    b = await client.post(...)
    # Try to supersede A claiming version 1 — should conflict
    c = await client.post(...)
    assert c.status_code == 409
```

## Dependencies
- Phase 1.1 (client_uuid UNIQUE constraint, version column)
- Phase 1.2 (write path exists)
