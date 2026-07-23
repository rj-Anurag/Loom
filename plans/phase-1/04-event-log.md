---
title: "Phase 1.4 — Event Log (Append-Only Ledger)"
description: "The immutable, append-only event log that serves as the system's source of truth. Every write, merge, and conflict is recorded here."
status: pending
dependencies: ["phase-1/02-context-service-write.md"]
---

# Event Log (Append-Only Ledger)

## Description
The event log is Loom's architectural guarantee that nothing is ever lost. Every write to the context store produces an immutable event. The `context_units` and `context_edges` tables are projections that can be rebuilt from this log at any time.

## Implementation

### Core Write Path
In `services/context/service.py`, every write must also append to `event_log`:

```python
async def append_event(conn, project_id, event_type, payload):
    await conn.execute("""
        INSERT INTO event_log (project_id, event_type, payload)
        VALUES ($1, $2, $3::jsonb)
    """, project_id, event_type, json.dumps(payload))
```

Payload schema per event type:

**write**:
```json
{
    "context_unit_id": "uuid",
    "client_uuid": "uuid",
    "agent_id": "uuid",
    "type": "message",
    "trust_tier": "agent",
    "content_preview": "first 200 chars...",
    "parent_ids": ["uuid1"],
    "parent_relations": ["derived_from"],
    "version": 1
}
```

**merge**:
```json
{
    "target_id": "uuid",
    "source_ids": ["uuid1", "uuid2"],
    "merge_strategy": "auto_merge|manual_resolve",
    "resolved_by": "agent_id"
}
```

**conflict_flagged**:
```json
{
    "context_unit_id": "uuid",
    "conflicting_unit_ids": ["uuid1", "uuid2"],
    "conflict_type": "version_mismatch|overlapping_content",
    "pending_branch_id": "uuid"
}
```

### Projection Rebuild Script
Create `scripts/rebuild-projections.sh` that:
1. Truncates `context_units` and `context_edges` (but NOT `event_log`)
2. Replays all events in chronological order
3. Rebuilds the graph structure from event payloads

### Immutability Enforcement
- Database-level triggers prevent UPDATE and DELETE on `event_log`
- Application-level: the `write_context` function never calls `UPDATE event_log SET ...`
- If a projection rebuild is needed, it always replays from the log — never from a backup of projections

### Event Log Integrity
- Each event includes a `content_hash` field (SHA-256 of the payload)
- Optional: periodic integrity check that recomputes hashes and reports mismatches

## File Targets
- `services/context/service.py` — event appending logic (already partially done in write path)
- `scripts/rebuild-projections.sh` — rebuild script
- `services/context/migrations/008_enforce_event_log_immutability.sql` — triggers

## Acceptance Criteria

- [ ] Every successful write produces an event_log row
- [ ] Event log is queryable by project_id and chronological order
- [ ] `UPDATE event_log SET ...` fails at the database level
- [ ] `DELETE FROM event_log` fails at the database level
- [ ] Rebuild script can reconstruct the context graph from the event log
- [ ] Rebuild is idempotent (running it twice produces the same result)

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_write_produces_event_log_entry(db, test_project, test_agent):
    # Write a context unit
    # Verify event_log has one new row
    pass

@pytest.mark.asyncio
async def test_event_log_is_immutable(db):
    with pytest.raises(Exception):
        await db.execute("UPDATE event_log SET payload = '{}'::jsonb")
    with pytest.raises(Exception):
        await db.execute("DELETE FROM event_log")

@pytest.mark.asyncio
async def test_rebuild_reconstructs_graph(db, sample_context_graph):
    # Record the expected state
    # Truncate context_units and context_edges
    # Run rebuild
    # Verify graph matches expected state
    pass
```

## Dependencies
- Phase 1.1 (event_log table exists)
- Phase 1.2 (write path produces events)
