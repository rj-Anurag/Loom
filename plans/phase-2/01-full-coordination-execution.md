---
title: "Phase 2.1 — Full Coordination Service (Execution Plan)"
description: "Redis-backed distributed locks, git-style branch/merge, task assignment. Architect-approved with 9 refinements."
status: completed
dependencies: ["phase-1/08-basic-coordination.md"]
---

# Full Coordination Service — Execution Plan

## Prerequisites

| # | Task | Check |
|---|---|---|
| P0 | Install Redis (`brew install redis` on macOS, then `brew services start redis`) | `redis-cli ping` → PONG |
| P1 | Ensure PostgreSQL is running (needed for integration tests) | `pg_isready` |

---

## Subtask Index

| ID | Name | Est. Time | Depends On |
|---|---|---|---|
| A1 | Create Branch + Task SQLAlchemy models + migrations | 30 min | — |
| A2 | Extend PendingBranch model with branch_id FK | 15 min | A1 |
| B1 | Implement Redis lock module (locks.py) | 30 min | P0, A1 |
| B2 | Implement branch CRUD + merge logic (branches.py) | 45 min | B1 |
| C1 | Implement task CRUD + state machine (tasks.py) | 30 min | A1 |
| D1 | Create CoordinationService class (service.py) | 30 min | B1, B2, C1 |
| D2 | Wire CoordinationService into write_context | 30 min | D1 |
| E1 | Create branch API router (branches.py) | 20 min | B2 |
| E2 | Create task API router (tasks.py) | 20 min | C1 |
| E3 | Extend conflicts API router with branch_id | 15 min | A2 |
| E4 | Register new routers | 5 min | E1, E2, E3 |
| F1 | Write Redis lock tests | 20 min | B1 |
| F2 | Write branch CRUD + merge integration tests | 30 min | B2 |
| F3 | Write task lifecycle integration tests | 20 min | C1 |
| F4 | Extend existing coordination tests for new write path | 20 min | D2 |

**Total estimated time: ~5.5 hours**

---

## A1 — Branch + Task Models

### Files
- **CREATE** `loom/models/branches.py` — Branch SQLAlchemy model
- **CREATE** `loom/models/tasks.py` — Task SQLAlchemy model
- **MODIFY** `loom/models/__init__.py` — export Branch, Task
- **CREATE** `loom/services/context/migrations/009_create_branches.sql`
- **CREATE** `loom/services/context/migrations/010_create_tasks.sql`

### Branch Model
```python
class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        default="open",
    )
    source_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    merged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'merging', 'merged', 'abandoned')",
            name="ck_branches_status",
        ),
        UniqueConstraint("project_id", "name", name="uq_branches_project_name"),
    )
```

### Task Model
```python
class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        default="pending",
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')",
            name="ck_tasks_status",
        ),
    )
```

### Migrations
**009_create_branches.sql:**
```sql
CREATE TABLE IF NOT EXISTS branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    status          TEXT DEFAULT 'open'
                    CHECK (status IN ('open', 'merging', 'merged', 'abandoned')),
    source_branch_id UUID REFERENCES branches(id),
    created_by      UUID NOT NULL REFERENCES agents(id),
    task_id         UUID REFERENCES tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_at       TIMESTAMPTZ,
    UNIQUE(project_id, name)
);
```

**010_create_tasks.sql:**
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'pending'
                CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
    assigned_to UUID REFERENCES agents(id),
    branch_id   UUID REFERENCES branches(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Acceptance Criteria
- [x] `Branch` model creates with all columns and constraints
- [x] `Task` model creates with all columns and constraints
- [x] SQL migration files produce correct schema when applied
- [x] Models export from `loom.models.Branch` and `loom.models.Task`
- [x] Unique constraint on (project_id, name) for branches
- [x] Check constraints on status values for both tables

---

## A2 — Extend PendingBranch with branch_id

### Files
- **MODIFY** `loom/models/pending_branches.py` — add `branch_id` FK column
- **MODIFY** `loom/services/context/migrations/006_create_pending_branches.sql` — add branch_id column (or create 011_alter)
- **CREATE** `loom/services/context/migrations/011_alter_pending_branches_add_branch_id.sql`

### Changes
Add to PendingBranch model:
```python
branch_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
)
```

Migration SQL:
```sql
ALTER TABLE pending_branches ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id);
```

### Acceptance Criteria
- [x] `PendingBranch.branch_id` is nullable FK to branches
- [x] Existing pending_branches without branch_id remain valid
- [x] New pending_branches can optionally link to a branch
- [x] Migration is idempotent (IF NOT EXISTS)

---

## B1 — Redis Lock Module (locks.py)

### Files
- **CREATE** `loom/services/coordination/locks.py`

### Design (per Architect Review)
- Use `redis.set(key, val, nx=True, ex=TTL)` atomic lock (NOT setnx + expire)
- Lock key format: `lock:context_unit:{unit_id}`
- Multi-lock acquire with sorted UUID order (prevent deadlocks)
- Exponential backoff on acquire failure (100ms base, 3 retries)
- Graceful Redis-down fallback to optimistic concurrency mode
- Module-level lock: `lock:project:{project_id}` (coarse, for project ops)
- Lock timeout: 30s default

### Interface
```python
from dataclasses import dataclass

@dataclass
class LockResult:
    acquired: bool
    mode: Literal["redis", "optimistic"]  # for observability

async def acquire_lock(
    redis: redis_async.Redis,
    unit_id: str,
    agent_id: str,
    ttl: int = 30,
    retry_delay: float = 0.1,
    max_retries: int = 3,
) -> LockResult: ...

async def release_lock(
    redis: redis_async.Redis,
    unit_id: str,
    agent_id: str,
) -> bool: ...

async def acquire_locks(
    redis: redis_async.Redis,
    unit_ids: list[str],
    agent_id: str,
    ttl: int = 30,
) -> list[LockResult]: ...
   # Acquires multiple locks in sorted UUID order.
   # Releases all acquired locks if any acquire fails (all-or-nothing).
```

### Acceptance Criteria
- [x] Lock acquired exclusively — second acquire for same key returns False
- [x] Lock auto-releases after TTL
- [x] Lock released only by same agent that acquired it
- [x] Multi-lock acquire acquires in sorted UUID order
- [x] Multi-lock all-or-nothing: partial failure releases all acquired locks
- [x] Exponential backoff retries on contention (3 retries, 100ms base)
- [x] Redis-down returns LockResult(acquired=True, mode="optimistic")
- [x] Module can be used standalone (no dependency on CoordinationService)

---

## B2 — Branch CRUD + Merge Logic (branches.py)

### Files
- **CREATE** `loom/services/coordination/branches.py`

### Interface
```python
from dataclasses import dataclass

@dataclass
class MergeResult:
    status: Literal["merged", "conflict", "nothing_to_merge"]
    merge_unit_id: str | None = None
    conflict_ids: list[str] = field(default_factory=list)

async def create_branch(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    agent_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    source_branch_id: uuid.UUID | None = None,
) -> Branch: ...

async def list_branches(
    session: AsyncSession,
    project_id: uuid.UUID,
    status: str | None = None,
) -> list[Branch]: ...

async def merge_branch(
    session: AsyncSession,
    redis: redis_async.Redis,
    branch_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> MergeResult: ...
   # 1. Acquire locks on all units in the branch
   # 2. For each unit, check conflict with units on target (main)
   # 3. Non-overlapping → auto-merge (using existing merge.py helpers)
   # 4. Overlapping → flag as conflict (create PendingBranch with branch_id)
   # 5. Update branch status to 'merged' or leave as 'open' + create PendingBranch
   # 6. Release locks
```

### Acceptance Criteria
- [x] Creating a branch persists it with status='open'
- [x] Listing branches returns project-scoped branches
- [x] Merging a branch with non-conflicting units creates merge unit + edges
- [x] Merging a branch with conflicting units creates PendingBranch with branch_id
- [x] Merging an already-merged branch returns status="nothing_to_merge"
- [x] Branch name uniqueness enforced per project

---

## C1 — Task CRUD + State Machine (tasks.py)

### Files
- **CREATE** `loom/services/coordination/tasks.py`

### Interface
```python
async def create_task(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    description: str | None = None,
) -> Task: ...

async def list_tasks(
    session: AsyncSession,
    project_id: uuid.UUID,
    status: str | None = None,
) -> list[Task]: ...

async def assign_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> Task: ...
   # Sets assigned_to + status → 'assigned'

async def start_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    branch_id: uuid.UUID,
) -> Task: ...
   # Sets branch_id + status → 'in_progress'

async def complete_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> Task: ...
   # Sets status → 'completed'. Branch merge is separate (caller responsibility)

async def fail_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> Task: ...
   # Sets status → 'failed'
```

### State Machine
```
pending → assigned → in_progress → completed
                                   → failed
                               (any state) → failed
```

### Acceptance Criteria
- [x] Task can transition through full lifecycle: pending → assigned → in_progress → completed
- [x] Task can be marked failed from any non-terminal state
- [x] Listing tasks filters by project and optional status
- [x] Assigning a task sets assigned_to and status
- [x] Starting a task links branch_id and sets in_progress

---

## D1 — CoordinationService Class (service.py)

### Files
- **CREATE** `loom/services/coordination/service.py` — CoordinationService class
- **MODIFY** `loom/services/coordination/__init__.py` — export CoordinationService

### Design
```python
class CoordinationService:
    def __init__(
        self,
        session: AsyncSession,
        redis: redis_async.Redis | None = None,
    ):
        self.session = session
        self.redis = redis

    # Locks — delegates to locks.py
    async def acquire_lock(self, unit_id: str, agent_id: str) -> LockResult: ...
    async def acquire_locks(self, unit_ids: list[str], agent_id: str) -> list[LockResult]: ...
    async def release_lock(self, unit_id: str, agent_id: str) -> bool: ...

    # Branches — delegates to branches.py
    async def create_branch(self, ...) -> Branch: ...
    async def list_branches(self, ...) -> list[Branch]: ...
    async def merge_branch(self, branch_id, agent_id) -> MergeResult: ...

    # Tasks — delegates to tasks.py
    async def create_task(self, ...) -> Task: ...
    async def assign_task(self, ...) -> Task: ...
    async def start_task(self, ...) -> Task: ...
    async def complete_task(self, ...) -> Task: ...
```

### Redis Connection
Accept an optional redis client in the constructor. If None, try `get_redis()` from the queue module. If that also fails (not installed), all lock operations return optimistic mode.

### Acceptance Criteria
- [x] CoordinationService exposes unified API for locks, branches, tasks
- [x] Locks fall back to optimistic concurrency when Redis is unavailable
- [x] Service can be constructed with or without explicit redis client
- [x] All existing merge.py functions remain accessible (no breaking changes)

---

## D2 — Wire CoordinationService into write_context

### Files
- **MODIFY** `loom/services/context/service.py` — replace inline merge.py imports with CoordinationService
- **MODIFY** `loom/api/routers/context.py` — pass CoordinationService to write_context

### Write Path Changes (in `write_context`)

Current flow:
```
validate project → validate agent → type check → content check →
idempotency check → version-conflict check (with inline merge.py calls) →
create unit → create edges → auto-merge (inline import) → event log → commit
```

Phase 2.1 flow:
```
validate project → validate agent → type check → content check →
idempotency check →
[NEW] acquire_lock(parent_ids, agent_id)  ← BEFORE version check
version-conflict check →
  if conflict: [NEW] associate PendingBranch with current branch_id
  if non-overlapping: [NEW] CoordinationService.merge_branch() ← not inline
  if clean: proceed
create unit → create edges → event log →
[NEW] release_lock(parent_ids, agent_id)  ← AFTER write
commit
```

**Key change**: `write_context` takes an optional `branch_id` parameter. When provided and a version conflict occurs, the resulting PendingBranch is linked to the branch_id.

### Lock-Acquire Timing
Lock is acquired BEFORE the version check to avoid TOCTOU race:
1. Acquire Redis lock on parent units (or fall back to optimistic)
2. Read parent versions
3. Check version match
4. If OK, write + commit in Postgres
5. Release Redis lock (after commit)

### API Router Changes
The `write_context` endpoint signature doesn't need to change at the HTTP level — the CoordinationService is injected as a dependency. However, accept an optional `branch_id` in the request body:

```python
class WriteContextBody(BaseModel):
    client_uuid: uuid.UUID
    type: str
    content: str
    version: int
    trust_tier: str | None = None
    parent_ids: list[str] | None = None
    parent_relations: list[str] | None = None
    branch_id: str | None = None  # NEW — optional, for branch-aware writes
```

### Acceptance Criteria
- [x] Locks acquired before version check in write path
- [x] TOCTOU race eliminated (lock → check → write → unlock ordering)
- [x] Non-overlapping conflict triggers CoordinationService.merge_branch() not inline import
- [x] Overlapping conflict creates PendingBranch with branch_id when provided
- [x] Redis-down fallback: writes succeed with optimistic mode
- [x] All existing Phase 1.8 tests still pass (backward compatible)
- [x] Existing clients without branch_id continue to work

---

## E1 — Branch API Router

### Files
- **CREATE** `loom/api/routers/branches.py`

### Endpoints
```
POST   /v1/projects/{project_id}/branches          → Create branch
GET    /v1/projects/{project_id}/branches          → List branches
GET    /v1/projects/{project_id}/branches/{id}     → Get branch
POST   /v1/projects/{project_id}/branches/{id}/merge → Merge branch
```

### Acceptance Criteria
- [x] Create branch returns 201 with branch data
- [x] List branches returns 200 with branch list (filterable by status)
- [x] Get branch returns 200 with single branch
- [x] Merge branch returns 200 with merge result (merged/conflict/nothing_to_merge)
- [x] Merge non-existent branch returns 404
- [x] Merge already-merged branch returns 400

---

## E2 — Task API Router

### Files
- **CREATE** `loom/api/routers/tasks.py`

### Endpoints
```
POST   /v1/projects/{project_id}/tasks              → Create task
GET    /v1/projects/{project_id}/tasks              → List tasks
GET    /v1/projects/{project_id}/tasks/{id}         → Get task
POST   /v1/projects/{project_id}/tasks/{id}/assign  → Assign task to agent
POST   /v1/projects/{project_id}/tasks/{id}/start   → Start task (link branch)
POST   /v1/projects/{project_id}/tasks/{id}/complete → Complete task
POST   /v1/projects/{project_id}/tasks/{id}/fail    → Fail task
```

### Acceptance Criteria
- [x] Full lifecycle endpoints work with correct state transitions
- [x] Invalid state transitions return 400 with error detail
- [x] List filters by optional status parameter
- [x] Non-existent task returns 404
- [x] Assigning to non-existent agent returns 404

---

## E3 — Extend Conflicts Router with branch_id

### Files
- **MODIFY** `loom/api/routers/conflicts.py`

### Changes
- Include `branch_id` in conflict list response (nullable)
- Accept optional `branch_id` in conflict creation (via context.py)
- When resolving, optionally update branch status if all conflicts on a branch are resolved

### Acceptance Criteria
- [x] Conflict list response includes `branch_id` field
- [x] Backward compatible — old conflicts (no branch_id) return null
- [x] Existing conflict tests continue to pass

---

## E4 — Register New Routers

### Files
- **MODIFY** `loom/api/routers/__init__.py` or the app factory

### Actions
- Register `branches.py` and `tasks.py` routers
- Ensure path prefix /v1 is consistent

### Acceptance Criteria
- [x] All new endpoints accessible at expected paths
- [x] No import errors at app startup

---

## F1 — Redis Lock Tests

### Files
- **CREATE** `tests/integration/test_locks.py`

### Test Scenarios
```python
async def test_acquire_release_lock(mock_redis):
    result = await acquire_lock(mock_redis, "unit-1", "agent-a")
    assert result.acquired is True
    assert result.mode == "redis"

async def test_lock_exclusivity(mock_redis):
    await acquire_lock(mock_redis, "unit-1", "agent-a")
    result = await acquire_lock(mock_redis, "unit-1", "agent-b")
    assert result.acquired is False

async def test_lock_ttl_expiry(mock_redis):
    # Use mock with time control

async def test_release_only_by_owner(mock_redis):
    # Agent B cannot release agent A's lock

async def test_multi_lock_ordering(mock_redis):
    # Locks acquired in sorted UUID order
    # All-or-nothing on partial failure

async def test_redis_down_fallback(mock_redis):
    # Simulate ConnectionError → returns optimistic mode
```

**Note**: These tests require a mock Redis client or a real Redis instance. Use fakeredis or `redis.from_url` with a test config.

---

## F2 — Branch CRUD + Merge Integration Tests

### Files
- **CREATE** `tests/integration/test_branches.py`

### Test Scenarios
```python
async def test_create_branch(client, test_project, auth_headers):
    resp = await client.post(...)
    assert resp.status_code == 201

async def test_list_branches(client, test_project, auth_headers):
    # Create 2 branches, list, verify both returned

async def test_merge_empty_branch(client, test_project, auth_headers):
    # Merge an empty branch → "nothing_to_merge"

async def test_merge_non_conflicting_branch(...):
    # Branch with units that don't overlap with main → auto-merge

async def test_merge_conflicting_branch(...):
    # Branch with units that overlap → conflict + PendingBranch

async def test_merge_already_merged_branch(...):
    # Second merge → 400 / "nothing_to_merge"
```

---

## F3 — Task Lifecycle Integration Tests

### Files
- **CREATE** `tests/integration/test_tasks.py`

### Test Scenarios
```python
async def test_full_lifecycle(client, test_project, auth_headers):
    # Create → assign → start (with branch) → complete

async def test_invalid_transition(client, test_project, auth_headers):
    # Try to complete a pending task (not started) → 400

async def test_assign_nonexistent_agent(client, test_project, auth_headers):
    # → 404

async def test_list_by_status(client, test_project, auth_headers):
    # Create tasks with different statuses, filter
```

---

## F4 — Extend Existing Coordination Tests

### Files
- **MODIFY** `tests/integration/test_coordination.py`

### Additions
- Test that `write_context` with `branch_id` links PendingBranch to branch
- Test that lock acquire runs before version check (observable via mode)
- Test that Redis-down path works end-to-end
- Test backward compatibility (no branch_id → same behavior as Phase 1.8)

---

## Execution Order

```
P0 (Redis install)
  │
  ▼
A1 (Branch + Task models + migrations)
  │
  ├──▶ A2 (Extend PendingBranch) ──▶ E3 (Extend conflicts router)
  │
  ├──▶ B1 (locks.py)
  │       │
  │       └──▶ B2 (branches.py) ──▶ E1 (Branch API router)
  │
  ├──▶ C1 (tasks.py) ──▶ E2 (Task API router)
  │
  └──▶ D1 (CoordinationService) ──▶ D2 (Wire into write_context)
                                      │
                                      └──▶ E4 (Register routers)
                                             │
                                             ▼
                                      F1, F2, F3, F4 (Tests)
```

The ordering ensures:
- Models exist before services that use them
- locks.py is standalone and can be tested immediately after Redis
- Tasks depend only on models, not on branches/locks
- CoordinationService is the integration point that ties everything together
- API routers are thin wrappers over the service layer
- Tests run last (they depend on all code being in place)
