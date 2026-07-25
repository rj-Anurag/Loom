---
title: "Phase 2.4 — Redis Live Presence Execution Plan"
description: "Agent heartbeat tracking, live status, and presence querying via Redis. Powers the 'who's working' view for the browser extension (Phase 2.5)."
status: completed
dependencies: ["phase-2/01-full-coordination.md"]
---

# Redis Live Presence — Execution Plan

## Prerequisites

| # | Task | Check |
|---|---|---|
| P0 | Redis running on localhost:6379 | `redis-cli ping` → `PONG` |
| P1 | `loom/services/coordination/locks.py` — Redis lock infra exists (Phase 2.1) | File exists with `acquire_lock`, `release_lock`, `LockResult` |
| P2 | `loom/api/auth.py` — `require_auth()` with `AuthContext(agent_id)` | Exists |
| P3 | `tests/conftest.py` — `redis_client` fixture (DB 1, flush before/after) | Exists |

---

## Subtask Index

| ID | Name | Est. Time | Depends On |
|---|---|---|---|
| **A** | **Domain logic** | | |
| A1 | Create `loom/services/coordination/presence.py` — `record_heartbeat()`, `get_active_agents()`, `get_agent_presence()` | 30 min | P0, P1 |
| A2 | Create `loom/schemas/events.py` — event type enums for Phase 2.5 | 10 min | — |
| **B** | **API layer** | | |
| B1 | Create `loom/api/dependencies.py` — `get_redis` FastAPI dependency | 15 min | P0 |
| B2 | Update `loom/api/routers/agents.py` — heartbeat endpoint with auth + body model + presence service | 30 min | A1, B1 |
| B3 | Add `GET /v1/projects/{project_id}/agents/presence` endpoint to `agents.py` router | 20 min | A1, B1 |
| **C** | **Tests** | | |
| C1 | Write unit tests for `record_heartbeat`, `get_active_agents`, `get_agent_presence` | 25 min | A1 |
| C2 | Write integration tests for heartbeat endpoint (auth, body, expiry, Redis-down) | 25 min | B2 |
| C3 | Write integration tests for presence query endpoint | 15 min | B3 |
| **D** | **Plan update** | | |
| D1 | Update plan status and verify all tests pass | 10 min | C1, C2, C3 |

**Total estimated time: ~2.8 hours**

---

## Design Decisions (per Architect Review)

| # | Decision | Detail |
|---|---|---|
| 1 | **Use `SCAN` not `KEYS`** | `get_active_agents()` iterates keys via `SCAN 0 MATCH presence:agent:*` to avoid blocking Redis on large datasets. |
| 2 | **Create `Depends(get_redis)` in `loom/api/dependencies.py`** | New shared FastAPI dependency file. Uses `from loom.services.retrieval.queue import get_redis as _get_redis` to reuse the existing module-level singleton pattern. |
| 3 | **Heartbeat endpoint requires auth + agent_id match** | `require_auth()` returns `AuthContext(agent_id)`. The route verifies `auth.agent_id == agent_id` and returns 403 if mismatched. |
| 4 | **Lock monitoring deferred to Phase 2.5** | No lock monitoring in this phase. |
| 5 | **Offline agent lock release deferred** | Lock TTL is sufficient for now (30s default). No explicit cleanup. |
| 6 | **Use existing `agents.py` router** | All presence endpoints live in `loom/api/routers/agents.py`. |
| 7 | **WebSocket events: schema only** | `loom/schemas/events.py` defines event type enums — no WebSocket implementation. |
| 8 | **Simplify Redis hash** | Keys are `presence:agent:{agent_id}` with hash fields: `project_id`, `status`, `task_id`. Dropped: `agent_id`, `last_seen`, `ip_address`. |
| 9 | **All presence functions accept `redis=None`** | Graceful degradation: `redis=None` → heartbeat is a no-op, query returns `[]`. |

---

## A1 — `presence.py`: Heartbeat recording + presence querying

### Files
- **CREATE** `loom/services/coordination/presence.py`

### Constants

```python
PRESENCE_KEY_PREFIX = "presence:agent:"
HEARTBEAT_TTL = 60  # seconds — agent is "offline" after this without a heartbeat
SCAN_COUNT = 100    # batch size for SCAN iteration
```

### Functions

#### `record_heartbeat(redis, agent_id, project_id, status, task_id=None)`

```python
async def record_heartbeat(
    redis: redis_async.Redis | None,
    agent_id: str,
    project_id: str,
    status: str,
    task_id: str | None = None,
) -> bool:
    """Record or refresh an agent heartbeat in Redis.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → no-op (returns False).
    agent_id : str
        Unique agent identifier (stringified UUID).
    project_id : str
        Project the agent belongs to.
    status : str
        One of ``"idle"``, ``"working"``, ``"blocked"``.
    task_id : str | None
        Optional task UUID the agent is currently working on.

    Returns
    -------
    bool
        ``True`` if heartbeat was recorded, ``False`` if Redis was unavailable.

    Notes
    -----
    Uses ``HSET`` + ``EXPIRE``.  The TTL serves as the offline timeout —
    if an agent stops sending heartbeats, the key auto-expires.
    """
    if redis is None:
        return False

    key = f"{PRESENCE_KEY_PREFIX}{agent_id}"
    try:
        mapping: dict[str, str] = {
            "project_id": project_id,
            "status": status,
        }
        if task_id is not None:
            mapping["task_id"] = task_id

        await redis.hset(key, mapping=mapping)  # type: ignore[arg-type]
        await redis.expire(key, HEARTBEAT_TTL)
        return True
    except (ConnectionError, TimeoutError, OSError,
            redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
        logger.warning("Redis unavailable — heartbeat not recorded for agent %s", agent_id)
        return False
```

#### `get_active_agents(redis, project_id)`

```python
async def get_active_agents(
    redis: redis_async.Redis | None,
    project_id: str,
) -> list[dict[str, str]]:
    """Get all active agents in a project.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → returns empty list.
    project_id : str
        Project to filter by.

    Returns
    -------
    list[dict[str, str]]
        Each dict has keys: ``agent_id``, ``project_id``, ``status``,
        ``task_id`` (may be empty string).  Items without a matching
        ``project_id`` are filtered out.

    Notes
    -----
    Uses ``SCAN`` to iterate keys (not ``KEYS`` — avoids blocking Redis).
    Batch size is ``SCAN_COUNT`` (100).  Degrades gracefully to empty
    list when Redis is unreachable.
    """
    if redis is None:
        return []

    agents: list[dict[str, str]] = []
    cursor = 0
    try:
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{PRESENCE_KEY_PREFIX}*",
                count=SCAN_COUNT,
            )
            if keys:
                pipe = redis.pipeline()
                for key in keys:
                    pipe.hgetall(key)
                results = await pipe.execute()

                for key, data in zip(keys, results):
                    if data and data.get("project_id") == project_id:
                        agent_id = key[len(PRESENCE_KEY_PREFIX):]
                        entry: dict[str, str] = {
                            "agent_id": agent_id,
                            "project_id": data.get("project_id", ""),
                            "status": data.get("status", ""),
                            "task_id": data.get("task_id", ""),
                        }
                        agents.append(entry)

            if cursor == 0:
                break

        return agents
    except (ConnectionError, TimeoutError, OSError,
            redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
        logger.warning("Redis unavailable — returning empty active agents list")
        return []
```

#### `get_agent_presence(redis, agent_id)`

```python
async def get_agent_presence(
    redis: redis_async.Redis | None,
    agent_id: str,
) -> dict[str, str] | None:
    """Get the presence data for a single agent.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → returns None.
    agent_id : str
        Unique agent identifier.

    Returns
    -------
    dict[str, str] | None
        Presence data dict with keys ``agent_id``, ``project_id``,
        ``status``, ``task_id``, or ``None`` if the agent has no
        heartbeat record or Redis is down.
    """
    if redis is None:
        return None

    key = f"{PRESENCE_KEY_PREFIX}{agent_id}"
    try:
        data = await redis.hgetall(key)
        if not data:
            return None
        return {
            "agent_id": agent_id,
            "project_id": data.get("project_id", ""),
            "status": data.get("status", ""),
            "task_id": data.get("task_id", ""),
        }
    except (ConnectionError, TimeoutError, OSError,
            redis_exceptions.ConnectionError, redis_exceptions.TimeoutError):
        logger.warning("Redis unavailable — could not fetch presence for agent %s", agent_id)
        return None
```

### `__all__` exports

```python
__all__ = [
    "record_heartbeat",
    "get_active_agents",
    "get_agent_presence",
    "PRESENCE_KEY_PREFIX",
    "HEARTBEAT_TTL",
]
```

### Acceptance Criteria
- [ ] `record_heartbeat(redis, ...)` stores `project_id`, `status`, `task_id` in `presence:agent:{agent_id}` hash
- [ ] `record_heartbeat` sets TTL of `HEARTBEAT_TTL` (60s)
- [ ] `record_heartbeat(redis=None, ...)` returns `False` (no-op)
- [ ] `record_heartbeat` returns `True` on success
- [ ] `get_active_agents(redis, project_id)` returns only agents in the matching project
- [ ] `get_active_agents` uses `SCAN` (not `KEYS`) — verifiable by implementation
- [ ] `get_active_agents(redis=None, ...)` returns `[]`
- [ ] `get_active_agents` with no matching agents returns `[]`
- [ ] `get_agent_presence(redis, agent_id)` returns presence dict for active agent
- [ ] `get_agent_presence(redis, agent_id)` returns `None` for non-existent agent
- [ ] `get_agent_presence(redis=None, ...)` returns `None`
- [ ] After TTL expires, agent automatically disappears from presence queries (verified by test)

---

## A2 — `loom/schemas/events.py`: Event type enums

### Files
- **CREATE** `loom/schemas/__init__.py` (empty)
- **CREATE** `loom/schemas/events.py`

### Content

```python
"""Event type definitions for Phase 2.5 WebSocket broadcasting.

This module defines the event strings used for real-time presence
events.  Schema-only — no WebSocket implementation in this phase.
"""

from __future__ import annotations

from typing import Literal

# ── Agent presence events ──────────────────────────────────────────────────

AgentOnlineEventPayload = dict
"""``{ "agent_id": str, "kind": str, "status": str }``"""

AgentHeartbeatEventPayload = dict
"""``{ "agent_id": str, "status": str, "task_id": str }``"""

AgentOfflineEventPayload = dict
"""``{ "agent_id": str }``"""

AgentLockEventPayload = dict
"""``{ "agent_id": str, "context_unit_id": str }``"""

AgentUnlockEventPayload = dict
"""``{ "agent_id": str, "context_unit_id": str }``"""


# ── Event type literals (used as discriminator) ────────────────────────────

AgentEventType = Literal[
    "agent_online",
    "agent_heartbeat",
    "agent_offline",
    "agent_lock",
    "agent_unlock",
]

__all__ = [
    "AgentOnlineEventPayload",
    "AgentHeartbeatEventPayload",
    "AgentOfflineEventPayload",
    "AgentLockEventPayload",
    "AgentUnlockEventPayload",
    "AgentEventType",
]
```

### Acceptance Criteria
- [ ] File creates without import errors
- [ ] All type aliases are `dict` (no implementation, schema only)
- [ ] `AgentEventType` is a `Literal` type with exactly 5 members
- [ ] Module exports listed in `__all__`

---

## B1 — `loom/api/dependencies.py`: Shared FastAPI dependencies

### Files
- **CREATE** `loom/api/dependencies.py`

### Content

```python
"""Shared FastAPI dependencies for the Loom API.

Provides ``get_redis`` — a ``Depends``-compatible dependency that
reuses the existing module-level Redis singleton from the retrieval
queue module.
"""

from __future__ import annotations

from typing import AsyncGenerator

import redis.asyncio as redis_async

from loom.services.retrieval.queue import get_redis as _get_queue_redis


async def get_redis() -> AsyncGenerator[redis_async.Redis | None, None]:
    """FastAPI dependency that provides a Redis client or ``None``.

    Reuses the existing module-level Redis singleton from
    ``loom.services.retrieval.queue``.  If Redis is misconfigured
    the dependency degrades gracefully by yielding ``None``, which
    all presence functions handle via their ``redis=None`` paths.

    Yields
    ------
    redis_async.Redis | None
        Redis client, or ``None`` if the connection URL is not set
        or the client could not be initialised.
    """
    try:
        redis = _get_queue_redis()
        yield redis
    except Exception:
        yield None


__all__ = [
    "get_redis",
]
```

### Acceptance Criteria
- [ ] `get_redis` yields a working Redis client when Redis is available
- [ ] `get_redis` yields `None` when Redis is misconfigured/unreachable
- [ ] Reuses the module-level singleton (does not create a second connection pool)
- [ ] Importable without side effects

---

## B2 — Update `agents.py` router: heartbeat endpoint

### Files
- **MODIFY** `loom/api/routers/agents.py`

### Changes

#### 1. Add imports

```python
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import redis.asyncio as redis_async

from loom.api.auth import AuthContext, require_auth
from loom.api.dependencies import get_redis
from loom.services.coordination.presence import record_heartbeat
```

#### 2. Add HeartbeatRequest model

```python
class HeartbeatRequest(BaseModel):
    """JSON body for POST /v1/agents/{agent_id}/heartbeat."""

    status: Literal["idle", "working", "blocked"] = Field(
        ...,
        description="Current agent status.",
    )
    task_id: str | None = Field(
        None,
        description="Optional task UUID the agent is working on.",
    )
```

#### 3. Replace heartbeat stub

Replace the existing stub:

```python
@router.post("/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str) -> dict[str, Any]:
    return {"status": "ok"}
```

With:

```python
@router.post(
    "/agents/{agent_id}/heartbeat",
    responses={
        200: {"description": "Heartbeat recorded"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent ID mismatch"},
    },
)
async def agent_heartbeat(
    agent_id: uuid.UUID,
    body: HeartbeatRequest,
    auth: AuthContext = Depends(require_auth),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Record an agent heartbeat.

    The authenticated agent must match the ``agent_id`` path parameter.
    Heartbeat refreshes the agent's presence TTL in Redis.
    """
    # Verify agent_id matches auth
    if auth.agent_id != agent_id:
        raise HTTPException(
            status_code=403,
            detail="AGENT_ID_MISMATCH",
        )

    recorded = await record_heartbeat(
        redis=redis,
        agent_id=str(agent_id),
        project_id=str(auth.project_id) if hasattr(auth, 'project_id') else "",
        status=body.status,
        task_id=body.task_id,
    )

    return {
        "status": "ok",
        "redis_available": recorded,
    }
```

**Wait** — `AuthContext` only has `agent_id`, not `project_id`. We need to decide: does the heartbeat endpoint need `project_id`?

Architectural decision #3 says "Heartbeat endpoint requires auth + agent_id match". The `require_auth()` returns `AuthContext(agent_id)`. But the presence data model stores `project_id`.

Option A: Add `project_id` to `AuthContext` (requires modifying `auth.py` — loads the agent, we already have the session).
Option B: The heartbeat endpoint picks up `project_id` from the agent record (requires a DB call).
Option C: Accept `project_id` in the request body (trusted — the auth already gates on agent_id match).

Looking at the context: `Agent` has `project_id`. The `require_auth` already loads the agent. We can extend `AuthContext` to include `project_id`. This is the cleanest option.

Let me revise:

Extend `AuthContext` in `auth.py` to include `project_id`.

**Modified AuthContext:**

```python
class AuthContext:
    """Represents an authenticated agent."""

    def __init__(self, agent_id: uuid.UUID, project_id: uuid.UUID | None = None) -> None:
        self.agent_id = agent_id
        self.project_id = project_id
```

And update `require_auth`:

```python
    return AuthContext(agent_id=agent.id, project_id=agent.project_id)
```

This is a small change to auth.py that enables the heartbeat endpoint to know which project the agent belongs to.

Let me write this up properly.

#### Alternative: Heartbeat doesn't need project_id from the caller

Actually, re-reading the Redis hash — `record_heartbeat` needs `project_id` to store it. But since the auth already loads the `Agent` model (which has `project_id`), we can extend `AuthContext` to carry it. This is a minor, backward-compatible change to `auth.py`.

So the plan should include a **B2a** substep: Extend `AuthContext` with `project_id`.

### B2 subtasks breakdown

#### B2a — Extend `AuthContext` with `project_id`

- **MODIFY** `loom/api/auth.py`
- Add `project_id` parameter to `AuthContext.__init__`
- Update `require_auth()` to pass `agent.project_id`

#### B2b — Update heartbeat endpoint

- **MODIFY** `loom/api/routers/agents.py`
- Full heartbeat endpoint with auth, body validation, Redis-backed presence recording

### Acceptance Criteria
- [ ] `POST /v1/agents/{agent_id}/heartbeat` with valid auth + matching agent_id returns 200
- [ ] `POST /v1/agents/{agent_id}/heartbeat` with mismatched agent_id returns 403
- [ ] `POST /v1/agents/{agent_id}/heartbeat` without auth returns 401
- [ ] `POST /v1/agents/{agent_id}/heartbeat` with invalid status returns 422 (Pydantic validation)
- [ ] Heartbeat records `status`, `project_id`, and optional `task_id` in Redis
- [ ] Response includes `redis_available: true/false`

---

## B3 — Add presence query endpoint

### Files
- **MODIFY** `loom/api/routers/agents.py` (same file, append new route)

### New endpoint

```python
@router.get(
    "/projects/{project_id}/agents/presence",
    responses={
        200: {"description": "Active agents list"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent does not belong to this project"},
    },
)
async def get_project_agents_presence(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> list[dict[str, str]]:
    """Get all active agents in a project.

    Returns presence data (status, task_id) for each agent that has
    sent a heartbeat within the TTL window.
    """
    return await get_active_agents(redis, str(project_id))
```

### Acceptance Criteria
- [ ] `GET /v1/projects/{project_id}/agents/presence` returns list of active agents
- [ ] Response includes `agent_id`, `status`, `task_id` for each agent
- [ ] Returns empty list when no agents have heartbeats
- [ ] Returns empty list when Redis is down
- [ ] Requires valid auth

---

## C1 — Unit tests for presence.py

### Files
- **CREATE** `tests/services/coordination/test_presence.py`

### Test Scenarios

```python
"""Unit tests for Phase 2.4 — Redis Live Presence.

Tests the pure service functions in
``loom.services.coordination.presence`` using the ``redis_client``
fixture (real Redis on DB 1, flushed between tests).
"""

from __future__ import annotations

import pytest
import redis.asyncio as redis_async

from loom.services.coordination.presence import (
    PRESENCE_KEY_PREFIX,
    get_active_agents,
    get_agent_presence,
    record_heartbeat,
)


class TestRecordHeartbeat:
    """Tests for record_heartbeat."""

    async def test_records_presence(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat stores project_id, status, and optional task_id."""
        result = await record_heartbeat(
            redis_client, "agent-1", "proj-a", "working", task_id="task-42",
        )
        assert result is True

        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert data["project_id"] == "proj-a"
        assert data["status"] == "working"
        assert data["task_id"] == "task-42"

    async def test_sets_ttl(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat sets a TTL on the key."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "idle")
        ttl = await redis_client.ttl(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert 0 < ttl <= 60  # within HEARTBEAT_TTL

    async def test_updates_existing(self, redis_client: redis_async.Redis) -> None:
        """A second heartbeat updates the existing hash and refreshes TTL."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await record_heartbeat(redis_client, "agent-1", "proj-a", "idle")
        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert data["status"] == "idle"

    async def test_redis_none_is_noop(self) -> None:
        """redis=None returns False without error."""
        result = await record_heartbeat(None, "agent-1", "proj-a", "working")
        assert result is False

    async def test_without_task_id(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat without task_id stores empty string."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "blocked")
        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert "task_id" not in data


class TestGetActiveAgents:
    """Tests for get_active_agents."""

    async def test_returns_matching_project(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """Only agents in the requested project are returned."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await record_heartbeat(redis_client, "agent-2", "proj-a", "idle")
        await record_heartbeat(redis_client, "agent-3", "proj-b", "working")

        agents = await get_active_agents(redis_client, "proj-a")
        assert len(agents) == 2
        agent_ids = {a["agent_id"] for a in agents}
        assert agent_ids == {"agent-1", "agent-2"}

    async def test_empty_when_no_matches(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """Project with no agents returns empty list."""
        agents = await get_active_agents(redis_client, "proj-none")
        assert agents == []

    async def test_redis_none_returns_empty(self) -> None:
        """redis=None returns empty list."""
        agents = await get_active_agents(None, "proj-a")
        assert agents == []

    async def test_includes_all_fields(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """Each agent dict has agent_id, project_id, status, task_id."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "blocked", task_id="t1")
        agents = await get_active_agents(redis_client, "proj-a")
        assert len(agents) == 1
        entry = agents[0]
        assert entry["agent_id"] == "agent-1"
        assert entry["project_id"] == "proj-a"
        assert entry["status"] == "blocked"
        assert entry["task_id"] == "t1"


class TestGetAgentPresence:
    """Tests for get_agent_presence."""

    async def test_returns_presence_for_active_agent(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """Returns presence dict for an agent with a heartbeat."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        presence = await get_agent_presence(redis_client, "agent-1")
        assert presence is not None
        assert presence["agent_id"] == "agent-1"
        assert presence["status"] == "working"
        assert presence["project_id"] == "proj-a"

    async def test_returns_none_for_unknown_agent(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """Non-existent agent returns None."""
        presence = await get_agent_presence(redis_client, "ghost-agent")
        assert presence is None

    async def test_redis_none_returns_none(self) -> None:
        """redis=None returns None."""
        presence = await get_agent_presence(None, "agent-1")
        assert presence is None

    async def test_expired_agent_returns_none(
        self, redis_client: redis_async.Redis,
    ) -> None:
        """After TTL expiry, agent presence returns None."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await redis_client.expire(f"{PRESENCE_KEY_PREFIX}agent-1", 0)  # force expire
        presence = await get_agent_presence(redis_client, "agent-1")
        assert presence is None
```

### Acceptance Criteria
- [ ] All `TestRecordHeartbeat` tests pass
- [ ] All `TestGetActiveAgents` tests pass
- [ ] All `TestGetAgentPresence` tests pass
- [ ] Tests use `redis_client` fixture from `tests/conftest.py`

---

## C2 — Integration tests for heartbeat endpoint

### Files
- **CREATE** `tests/integration/test_presence.py`

### Fixtures

Reuse patterns from existing integration tests:
- `client` from `tests/conftest.py`
- `test_project`, `test_agent`, `auth_headers` from `test_coordination.py` pattern (or shared)
- `redis_client` from `tests/conftest.py`

### Test Scenarios

```python
"""Integration tests for Phase 2.4 — Redis Live Presence API.

Tests the heartbeat endpoint and presence query endpoint through
the FastAPI app.
"""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as redis_async
from httpx import AsyncClient

from loom.models import Agent, Project

# Shared fixture: reuse from conftest for client, redis_client
# Define test_project, test_agent, auth_headers inline (same pattern as test_coordination)


@pytest.mark.asyncio
async def test_heartbeat_records_and_returns_ok(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
    redis_client: redis_async.Redis,
) -> None:
    """Valid heartbeat returns 200 and records presence in Redis."""
    resp = await client.post(
        f"/v1/agents/{test_agent.id}/heartbeat",
        json={"status": "working"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["redis_available"] is True

    # Verify in Redis
    from loom.services.coordination.presence import PRESENCE_KEY_PREFIX
    presence = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}{test_agent.id}")
    assert presence["status"] == "working"


@pytest.mark.asyncio
async def test_heartbeat_auth_mismatch(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """Heartbeat with agent_id != auth.agent_id returns 403."""
    other_id = uuid.uuid4()
    resp = await client.post(
        f"/v1/agents/{other_id}/heartbeat",
        json={"status": "working"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "AGENT_ID_MISMATCH"


@pytest.mark.asyncio
async def test_heartbeat_without_auth(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
) -> None:
    """Heartbeat without auth returns 401."""
    resp = await client.post(
        f"/v1/agents/{test_agent.id}/heartbeat",
        json={"status": "working"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_heartbeat_invalid_status(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """Invalid status value returns 422."""
    resp = await client.post(
        f"/v1/agents/{test_agent.id}/heartbeat",
        json={"status": "invalid_status"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_heartbeat_with_task_id(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
    redis_client: redis_async.Redis,
) -> None:
    """Heartbeat with task_id stores it in Redis."""
    resp = await client.post(
        f"/v1/agents/{test_agent.id}/heartbeat",
        json={"status": "working", "task_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    from loom.services.coordination.presence import PRESENCE_KEY_PREFIX
    presence = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}{test_agent.id}")
    assert "task_id" in presence


@pytest.mark.asyncio
async def test_heartbeat_redis_down(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Redis is down, heartbeat returns ok with redis_available=false."""
    import loom.config
    original = loom.config.settings.redis_url
    loom.config.settings.redis_url = "redis://localhost:16379/1"
    # Reset module-level Redis singleton
    import loom.services.retrieval.queue as queue_module
    queue_module._redis = None

    try:
        resp = await client.post(
            f"/v1/agents/{test_agent.id}/heartbeat",
            json={"status": "working"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["redis_available"] is False
    finally:
        loom.config.settings.redis_url = original
        queue_module._redis = None
```

### Acceptance Criteria
- [ ] Valid heartbeat returns 200 and persists to Redis
- [ ] Auth mismatch returns 403
- [ ] Missing auth returns 401
- [ ] Invalid status body returns 422
- [ ] Task_id is stored when provided
- [ ] Redis-down returns 200 with `redis_available: false`

---

## C3 — Integration tests for presence query endpoint

### Files
- **APPEND** to `tests/integration/test_presence.py` (same file as C2)

### Test Scenarios

```python
@pytest.mark.asyncio
async def test_presence_query_returns_active_agents(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
    redis_client: redis_async.Redis,
) -> None:
    """Presence endpoint returns agents that have sent heartbeats."""
    # Send heartbeat first
    await client.post(
        f"/v1/agents/{test_agent.id}/heartbeat",
        json={"status": "working"},
        headers=auth_headers,
    )

    resp = await client.get(
        f"/v1/projects/{test_project.id}/agents/presence",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)
    assert len(agents) >= 1
    matching = [a for a in agents if a["agent_id"] == str(test_agent.id)]
    assert len(matching) == 1
    assert matching[0]["status"] == "working"


@pytest.mark.asyncio
async def test_presence_query_empty_when_no_heartbeats(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Project with no active agents returns empty list."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/agents/presence",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_presence_query_requires_auth(
    client: AsyncClient,
    test_project: Project,
) -> None:
    """Presence query without auth returns 401."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/agents/presence",
    )
    assert resp.status_code == 401
```

### Acceptance Criteria
- [ ] Presence query returns agents with active heartbeats
- [ ] Returns `[]` when no heartbeats exist
- [ ] Requires valid auth
- [ ] Results include `agent_id`, `status`, `task_id`

---

## Risks and Edge Cases

| Risk | Impact | Mitigation |
|---|---|---|
| **Redis connection pool exhaustion** | Queue module and presence module share one pool — if `get_redis()` creates a second pool, we get duplicate connections. | Reuse the existing module-level singleton in `queue.py`. `dependencies.py` calls `_get_queue_redis()` which returns the same client. |
| **SCAN vs KEYS on large datasets** | If thousands of agents are tracked, `SCAN` with `count=100` may be slow. | `SCAN_COUNT` is configurable. For Phase 2.4, 100 is adequate — no project will have >1000 active agents. |
| **TTL race on rapid heartbeats** | Agent sends heartbeat every 15s, TTL is 60s. If Redis expires the key between `HSET` and `EXPIRE`, the key could vanish. | `HSET` creates the key if missing. `EXPIRE` refreshes TTL. These are separate commands but the race window only causes early expiry, not data corruption. Use `HSET` + `EXPIRE` in a pipeline if this becomes an issue. |
| **`AuthContext` backward compatibility** | Adding `project_id` to `AuthContext` may break existing code that destructures it as `(agent_id,)`. | `project_id` defaults to `None` — all existing callers continue to work unchanged. |
| **Test isolation with shared Redis** | Tests using `redis_client` flush DB 1 between tests, which could interfere with parallel test runs. | All presence tests use the same `redis_client` fixture. No tests run in parallel (pytest default). |

---

## Execution Order

```
A1  ───→ C1
              │
B2a ───→ B2b ─→ C2
│               │
B1  ────────────┤
│               │
B3  ────────────→ C3
│
A2  (no deps, can run anytime)
│
D1  ───→ verify all tests pass
```

### Suggested execution sequence:

1. **A2** — `events.py` schema (trivial, no deps)
2. **B1** — `dependencies.py` (needed by B2b, B3)
3. **B2a** — Extend `AuthContext` with `project_id` (needed by B2b)
4. **A1** — `presence.py` (core logic, needed by B2b, B3, C1)
5. **C1** — Run unit tests for A1
6. **B2b** — Heartbeat endpoint
7. **B3** — Presence query endpoint
8. **C2, C3** — Integration tests
9. **D1** — Verify all tests pass, update plan status

---

## File Change Summary

| File | Action | Contents |
|---|---|---|
| `loom/schemas/__init__.py` | **CREATE** | Empty file |
| `loom/schemas/events.py` | **CREATE** | Event type literals and payload type aliases |
| `loom/api/dependencies.py` | **CREATE** | `get_redis` FastAPI dependency |
| `loom/services/coordination/presence.py` | **CREATE** | `record_heartbeat`, `get_active_agents`, `get_agent_presence` |
| `loom/api/auth.py` | **MODIFY** | Add `project_id` to `AuthContext` |
| `loom/api/routers/agents.py` | **MODIFY** | Heartbeat endpoint + presence query endpoint |
| `tests/services/coordination/test_presence.py` | **CREATE** | Unit tests for presence service |
| `tests/integration/test_presence.py` | **CREATE** | Integration tests for heartbeat + presence API |
| `plans/phase-2/04-live-presence.md` | **MODIFY** | Update status to completed after execution |
| `plans/phase-2/04-live-presence-execution.md` | **CREATE** | This execution plan |
