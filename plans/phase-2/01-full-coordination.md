---
title: "Phase 2.1 — Full Coordination Service"
description: "Separate Coordination Service with Redis-based locking, git-style branch/merge, fine-grained per-unit locks, and task assignment."
status: completed
dependencies: ["phase-1/08-basic-coordination.md"]
---

# Full Coordination Service

## Description
Evolve the basic coordination from Phase 1.8 into a full coordination service with Redis-backed distributed locks, git-style branch/merge semantics, per-Context-Unit granularity, and a task assignment system.

## Location
`services/coordination/` — evolve from the Phase 1 basic coordination.

## Redis Locking

### Lock Model
```python
async def acquire_lock(context_unit_id: str, agent_id: str, ttl: int = 30) -> bool:
    """Acquire a lock on a context unit. Returns True if acquired."""
    lock_key = f"lock:context_unit:{context_unit_id}"
    acquired = await redis.setnx(lock_key, agent_id)
    if acquired:
        await redis.expire(lock_key, ttl)
    return acquired

async def release_lock(context_unit_id: str, agent_id: str):
    """Release a lock only if held by this agent."""
    lock_key = f"lock:context_unit:{context_unit_id}"
    current = await redis.get(lock_key)
    if current == agent_id:
        await redis.delete(lock_key)
```

### Lock Hierarchy
- Per-Context-Unit locks (fine-grained, primary)
- Per-Project locks (coarse, only for project-level operations)
- Lock timeout: 30s default, extendable via heartbeat
- Deadlock detection: locks held > 60s without heartbeat are released

## Git-Style Branch/Merge

### Branch Model
```
main (trunk) ──► unit_1 ──► unit_2 ──► unit_3
                    │
                    └── branch_a ──► unit_2a ──► unit_2b
                                              │
                                              └── merge_back ──► unit_4
```

Each context unit has a `branch_id`:
- `None` = main trunk
- UUID = named branch

### Merge Strategies
```python
async def merge_branch(source_branch_id: str, target_branch_id: str = None):
    """
    Merge all units from source_branch into target_branch (or main).
    1. Find all units on source branch not on target
    2. For each unit, check for conflicts with units on target
    3. If no conflicts: auto-merge (create merge unit + edges)
    4. If conflicts: flag for resolution
    """
```

### Branch API
```
POST /v1/projects/{id}/branches  → Create a new branch
GET  /v1/projects/{id}/branches  → List branches
POST /v1/projects/{id}/branches/{id}/merge  → Merge branch
```

## Task Assignment

### How Tasks Flow
1. User creates a task (via extension sidebar or API)
2. Coordination Service records the task in a `tasks` table
3. Available agents poll or are notified of pending tasks
4. Agent accepts the task (creates a branch)
5. Agent works on the task (writes context units on the branch)
6. Agent completes the task (marks it done)
7. Coordination Service merges the branch
8. If merge conflicts → flag for user resolution

### Task Table Schema
```sql
CREATE TABLE tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'pending'
                CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
    assigned_to UUID REFERENCES agents(id),
    branch_id   UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Acceptance Criteria

- [ ] Redis locks are acquired and released correctly
- [ ] Locks expire after TTL and are auto-released
- [ ] Lock hierarchy prevents deadlocks
- [ ] Branch creation and listing works
- [ ] Branch merge auto-merges non-conflicting changes
- [ ] Branch merge flags conflicting changes for resolution
- [ ] Task assignment and completion workflow works end-to-end
- [ ] Multiple agents can work on different branches concurrently

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_redis_lock_acquire_release(redis_client):
    acquired = await acquire_lock("unit-1", "agent-a")
    assert acquired is True
    released = await release_lock("unit-1", "agent-a")
    assert released is True

@pytest.mark.asyncio
async def test_lock_expires(redis_client):
    await acquire_lock("unit-1", "agent-a", ttl=1)
    await asyncio.sleep(1.5)
    acquired = await acquire_lock("unit-1", "agent-b")
    assert acquired is True

@pytest.mark.asyncio
async def test_branch_merge_no_conflict(coordination_service, sample_branch):
    result = await coordination_service.merge_branch(sample_branch.id)
    assert result.status == "merged"

@pytest.mark.asyncio
async def test_branch_merge_with_conflict(coordination_service, conflicting_branch):
    result = await coordination_service.merge_branch(conflicting_branch.id)
    assert result.status == "conflict"
```

## Dependencies
- Phase 1.8 (basic coordination exists)
