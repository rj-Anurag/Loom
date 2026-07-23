---
title: "Phase 1.8 — Basic Coordination (Optimistic Concurrency)"
description: "Conflict detection on concurrent writes. Pending branches table. Auto-merge for non-overlapping writes."
status: pending
dependencies: ["phase-1/06-idempotency.md"]
---

# Basic Coordination (Optimistic Concurrency)

## Description
Implement the basic coordination layer that detects concurrent writes to the same parent context units. When a conflict is detected, the system creates a "pending branch" that can be auto-merged (if non-overlapping) or flagged for human review (if overlapping).

## Location
`services/coordination/` — new service directory for coordination logic.

## Files to Create
- `services/coordination/__init__.py`
- `services/coordination/merge.py` — merge detection and resolution logic
- `services/coordination/service.py` — coordination service orchestration

## Conflict Detection

Conflict detection happens during the write path (Phase 1.2). When `write_context` is called:

1. Check parent versions (from Phase 1.6)
2. If all parents are at their expected versions — no conflict, proceed
3. If any parent has been superseded by another write since the agent read it — potential conflict:
   - Check if the new write's content overlaps with the superseding write's content
   - **Non-overlapping**: auto-merge (both writes become children of the same parent)
   - **Overlapping**: flag as conflict, create pending_branch

### Overlap Detection (Simple v1)

```python
def detect_overlap(content_a: str, content_b: str) -> bool:
    """
    Simple heuristic: if both writes touch the same file path or
    function name (extracted from content), they overlap.
    """
    entities_a = extract_entities(content_a)
    entities_b = extract_entities(content_b)
    return bool(entities_a & entities_b)
```

For v1, this is a simple set-based check. In Phase 2, this becomes more sophisticated.

## Auto-Merge Logic

When two writes are non-overlapping and both derive from the same parent:

```sql
-- Both writes become children of the parent with 'derived_from' edges
INSERT INTO context_edges (parent_id, child_id, relation)
VALUES ($parent_id, $write_a_id, 'derived_from'),
       ($parent_id, $write_b_id, 'derived_from');

-- A new merge unit is created
INSERT INTO context_units (project_id, agent_id, client_uuid, type, content)
VALUES ($project_id, $system_agent_id, $merge_uuid, 'summary', $merge_content);

-- Both writes are parents of the merge
INSERT INTO context_edges (parent_id, child_id, relation)
VALUES ($write_a_id, $merge_id, 'merged_from'),
       ($write_b_id, $merge_id, 'merged_from');

-- Event log entry
INSERT INTO event_log (project_id, event_type, payload)
VALUES ($project_id, 'merge', $payload);
```

## Conflict Flagging

When writes overlap:

1. Create a `pending_branches` row
2. Both writes are stored as separate context units
3. A `conflict_flagged` event is appended to the event log
4. The conflict is surfaced via the API (and later, via the browser UI)

### Pending Branches Table
```sql
CREATE TABLE pending_branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_unit_id UUID NOT NULL REFERENCES context_units(id),
    conflict_type   TEXT NOT NULL,
    resolution      TEXT DEFAULT 'pending'
                    CHECK (resolution IN ('pending', 'auto_merged', 'resolved')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## API Endpoints

### List Pending Conflicts
```
GET /v1/projects/{project_id}/conflicts
Response: [{ "id": "uuid", "context_unit_id": "uuid",
             "conflict_type": "version_mismatch", "resolution": "pending" }]
```

### Resolve Conflict
```
POST /v1/projects/{project_id}/conflicts/{id}/resolve
Body: { "resolution": "accept_a|accept_b|merge", "content": "optional merged content" }
```

## Acceptance Criteria

- [ ] Concurrent non-overlapping writes to the same parent auto-merge
- [ ] Concurrent overlapping writes to the same parent create a pending_branch
- [ ] Conflict list endpoint returns pending conflicts
- [ ] Conflict resolution endpoint marks a conflict as resolved
- [ ] Event log records merge and conflict_flagged events
- [ ] Auto-merge creates a summary-type merge unit

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_non_overlapping_writes_auto_merge(client, test_project):
    # Two agents write different content based on same parent
    # Verify both exist and a merge unit was created
    pass

@pytest.mark.asyncio
async def test_overlapping_writes_create_conflict(client, test_project):
    # Two agents write overlapping content based on same parent
    # Verify a pending_branch was created
    pass

@pytest.mark.asyncio
async def test_conflict_resolution(client, test_project):
    # Create a conflict, resolve it, verify resolution
    pass
```

## Dependencies
- Phase 1.6 (versioning and conflict detection)
