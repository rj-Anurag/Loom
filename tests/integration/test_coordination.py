"""Integration tests for Phase 1.8 — Basic Coordination (auto-merge + conflict detection).

Tests cover:
- Non-overlapping concurrent writes auto-merge (both succeed, merge unit created)
- Overlapping concurrent writes create a PendingBranch
- Conflict list endpoint returns pending conflicts
- Conflict resolve endpoint marks conflict as resolved
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

try:
    import redis.asyncio as redis_async
except ImportError:
    redis_async = None  # type: ignore[assignment]  # not required for Phase 1.8 tests


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Coordination Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def auth_headers(test_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_agent.id}"}


# ── Overlap detection utility ────────────────────────────────────────────────


def test_extract_entities() -> None:
    """extract_entities finds file paths, function names, and imports."""
    from loom.services.coordination.merge import extract_entities

    content = "Modified src/auth/login.py and def authenticate_user() in lib/auth.py"
    entities = extract_entities(content)
    assert "src/auth/login.py" in entities
    assert "lib/auth.py" in entities
    assert "authenticate_user" in entities


def test_detect_overlap_true() -> None:
    """detect_overlap returns True when two texts mention the same entities."""
    from loom.services.coordination.merge import detect_overlap

    a = "Implemented login in src/auth/login.py"
    b = "Fixed bug in src/auth/login.py"
    assert detect_overlap(a, b) is True


def test_detect_overlap_false() -> None:
    """detect_overlap returns False when texts mention different entities."""
    from loom.services.coordination.merge import detect_overlap

    a = "Built Redis cache in src/cache/redis_client.py"
    b = "Set up PostgreSQL in src/db/postgres_conn.py"
    assert detect_overlap(a, b) is False


# ── Auto-merge: non-overlapping writes ────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_overlapping_writes_auto_merge(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Two non-overlapping writes to the same parent both succeed and create a merge unit."""
    # 1. Write parent unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement caching layer",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Agent B writes child C1 with correct version
    c1_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Built Redis cache in src/cache/redis_client.py",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=c1_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    c1_id = resp.json()["id"]

    # 3. Agent A writes child C2 with stale version (1 instead of 2) but non-overlapping content
    c2_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Set up PostgreSQL connection in src/db/postgres_conn.py",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 1,  # stale — but content doesn't overlap with C1
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=c2_body,
        headers=auth_headers,
    )
    # Auto-merge: write succeeds despite stale version
    assert resp.status_code == 201, f"Expected auto-merge, got {resp.status_code}: {resp.text}"
    c2_id = resp.json()["id"]

    # 4. Verify both units exist
    result = await db_session.execute(
        text("SELECT id, content FROM context_units WHERE id IN (:c1, :c2)"),
        {"c1": c1_id, "c2": c2_id},
    )
    rows = result.all()
    assert len(rows) == 2

    # 5. Verify a merge unit was created (has merged_from edges to both C1 and C2)
    merge_edges = await db_session.execute(
        text(
            "SELECT ce.parent_id, ce.child_id, ce.relation FROM context_edges ce "
            "WHERE ce.child_id IN ("
            "  SELECT ce2.child_id FROM context_edges ce2 "
            "  WHERE ce2.parent_id IN (:c1, :c2) AND ce2.relation = 'merged_from'"
            ")"
            "AND ce.relation = 'merged_from'"
        ),
        {"c1": c1_id, "c2": c2_id},
    )
    merge_rows = merge_edges.all()
    assert len(merge_rows) >= 2, "Expected at least 2 merged_from edges (C1→merge, C2→merge)"

    # 6. Verify the merge unit in context_units
    merge_unit_id = merge_rows[0].child_id
    merge_unit = await db_session.execute(
        text("SELECT type, content FROM context_units WHERE id = :uid"),
        {"uid": merge_unit_id},
    )
    mu = merge_unit.one_or_none()
    assert mu is not None
    assert mu.type == "summary"


# ── Overlapping writes create PendingBranch ───────────────────────────────────


@pytest.mark.asyncio
async def test_overlapping_writes_create_conflict(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Two overlapping writes to the same parent create a PendingBranch."""
    # 1. Write parent
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement authentication",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Agent B writes overlapping content
    b_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implementing JWT login in src/auth/login.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=b_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    _ = resp.json()["id"]

    # 3. Agent A tries to write overlapping content with stale version
    a_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implementing OAuth login in src/auth/login.py",  # same file!
        "parent_ids": [parent_id],
        "version": 1,  # stale
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=a_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409, f"Expected conflict, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["detail"] == "VERSION_CONFLICT"
    assert "pending_branch_id" in data

    # 4. Verify pending_branches exists
    branch_rows = await db_session.execute(
        text("SELECT id, conflict_type, resolution FROM pending_branches"),
    )
    branches = branch_rows.all()
    assert len(branches) >= 1
    matching = [b for b in branches if b.resolution == "pending"]
    assert len(matching) >= 1


# ── Conflict API endpoints ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_list_endpoint(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET conflicts returns pending conflicts."""
    # Create a conflict first
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement search",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # Write first child
    b_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Elasticsearch setup in src/search/es_client.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=b_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Write overlapping second child
    a_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Meilisearch setup in src/search/es_client.py",  # same file
        "parent_ids": [parent_id],
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=a_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409
    pending_branch_id = resp.json()["pending_branch_id"]

    # List conflicts
    resp = await client.get(
        f"/v1/projects/{test_project.id}/conflicts",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    conflicts = resp.json()
    assert isinstance(conflicts, list)
    matching = [c for c in conflicts if c["id"] == pending_branch_id]
    assert len(matching) >= 1
    assert matching[0]["conflict_type"] == "version_conflict"
    assert matching[0]["resolution"] == "pending"


@pytest.mark.asyncio
async def test_conflict_resolve_endpoint(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """POST resolve marks a conflict as resolved."""
    # Create a conflict
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement logging",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    b_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Structured logging in src/logging/logger.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=b_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    a_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "JSON logging in src/logging/logger.py",  # same file
        "parent_ids": [parent_id],
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=a_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409
    pending_branch_id = resp.json()["pending_branch_id"]

    # Resolve the conflict
    resp = await client.post(
        f"/v1/projects/{test_project.id}/conflicts/{pending_branch_id}/resolve",
        json={"resolution": "resolved"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # Verify resolution in DB
    result = await db_session.execute(
        text("SELECT resolution FROM pending_branches WHERE id = :bid"),
        {"bid": pending_branch_id},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.resolution == "resolved"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2.1 — Write path extensions (branch integration, lock ordering,
# Redis fallback, backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════

# Note: These tests use a real Redis connection for lock-related scenarios.
# The ``redis_client`` fixture (defined in ``tests/conftest.py``) connects
# to ``localhost:6379/1`` and flushes between tests.


@pytest.mark.asyncio
async def test_write_with_branch_id(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Writing context with a branch_id creates a PendingBranch linked to the branch.

    This validates that the ``branch_id`` column on ``pending_branches`` is
    populated when a branch-scoped write triggers a version conflict, enabling
    the merge endpoint to associate conflicts with branches.
    """
    # 1. Create a branch
    branch_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/write-with-branch"},
        headers=auth_headers,
    )
    assert branch_resp.status_code == 201
    branch_id = branch_resp.json()["id"]

    # 2. Write a parent context unit on main
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: refactor database layer",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 3. Write a unit on main (creates siblings)
    main_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Migrated ORM queries in src/db/repository.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=main_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # 4. Write overlapping content on the branch — use stale version (1 instead of 2)
    #    to trigger version-conflict detection
    branch_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Rewrote queries in src/db/repository.py with SQLAlchemy 2.0",
        "parent_ids": [parent_id],
        "version": 1,  # stale — parent is version 1, expected version is 2
        "branch_id": branch_id,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=branch_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409, f"Expected conflict, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "pending_branch_id" in data

    # 5. Verify the PendingBranch has the correct branch_id
    pending_id = data["pending_branch_id"]
    result = await db_session.execute(
        text("SELECT id, branch_id, resolution FROM pending_branches WHERE id = :pid"),
        {"pid": uuid.UUID(pending_id)},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.branch_id is not None, "pending_branches.branch_id should be set"
    assert str(row.branch_id) == branch_id
    assert row.resolution == "pending"


@pytest.mark.asyncio
async def test_write_without_branch_id_backward_compat(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Writing context without a branch_id behaves exactly as in Phase 1.8.

    The ``branch_id`` field is optional; when omitted the write path must
    fall back to the original conflict-detection behaviour (creates a
    PendingBranch with ``branch_id IS NULL``).
    """
    # 1. Write parent
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement search indexing",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Write first child (version 2)
    child1_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Set up Elasticsearch in src/search/es_client.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child1_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # 3. Write overlapping second child without branch_id — should produce conflict
    child2_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Set up Meilisearch in src/search/es_client.py",
        "parent_ids": [parent_id],
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child2_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409
    pending_branch_id = resp.json()["pending_branch_id"]

    # 4. Verify PendingBranch exists with branch_id IS NULL
    result = await db_session.execute(
        text("SELECT id, branch_id FROM pending_branches WHERE id = :pid"),
        {"pid": uuid.UUID(pending_branch_id)},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.branch_id is None, "Phase 1.8-style conflict should have branch_id IS NULL"


@pytest.mark.asyncio
async def test_write_context_lock_before_check(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    redis_client: redis_async.Redis,
) -> None:
    """The write path acquires a Redis lock on the parent unit BEFORE performing
    the version-conflict check.

    Locks are best-effort (fall back to optimistic concurrency per architecture).
    This test verifies that the lock acquisition happens without error, and that
    the version check still functions correctly with the lock held by a different
    agent (the write proceeds via optimistic fallback since the lock is advisory).
    """
    from loom.services.coordination.locks import acquire_lock, release_lock

    # 1. Write a parent context unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement rate limiting",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Manually acquire a Redis lock on the parent unit with a different agent id
    other_agent_id = str(uuid.uuid4())
    lock_result = await acquire_lock(redis_client, parent_id, other_agent_id, ttl=3)
    assert lock_result.acquired is True

    # 3. Write a child — should succeed because locks are best-effort
    #    (fall back to optimistic concurrency + version check)
    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implementing token bucket in src/ratelimit/token_bucket.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )
    # Lock held by other agent → lock acquisition returns acquired=False,
    # but the write still proceeds via optimistic concurrency.
    # Version 2 matches expected (parent v1 + 1), so write succeeds.
    assert resp.status_code == 201, (
        f"Write should succeed with optimistic fallback: {resp.status_code}: {resp.text}"
    )

    # 4. Release the lock
    await release_lock(redis_client, parent_id, other_agent_id)


@pytest.mark.asyncio
async def test_write_context_redis_down(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Redis is unreachable, the write path falls back to optimistic
    concurrency control (PostgreSQL-level version checking) and the write
    succeeds or fails based on content overlap, not Redis availability.
    """
    # 1. Monkey-patch the Redis connection to point at a dead port
    import loom.config

    original_redis_url = loom.config.settings.redis_url
    loom.config.settings.redis_url = "redis://localhost:16379/1"
    # Force re-initialization of the module-level Redis client
    import loom.services.retrieval.queue as queue_module

    # Reset the module-level _redis so get_redis() creates a new (broken) connection
    queue_module._redis = None  # type: ignore[attr-defined]

    try:
        # 2. Write parent (no Redis needed for this)
        parent_body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "Decision: implement audit logging",
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=parent_body,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        parent_id = resp.json()["id"]

        # 3. Write first child
        child1_body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "task_result",
            "content": "Audit trail in src/audit/logger.py",
            "parent_ids": [parent_id],
            "version": 2,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=child1_body,
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # 4. Write non-overlapping child with stale version (auto-merge via optimistic check)
        child2_body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "task_result",
            "content": "Audit dashboard in src/audit/dashboard.py",
            "parent_ids": [parent_id],
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=child2_body,
            headers=auth_headers,
        )
        # Should succeed (auto-merge) despite Redis being down
        assert resp.status_code == 201, (
            f"Should succeed with optimistic fallback, got {resp.status_code}: {resp.text}"
        )
    finally:
        # Restore Redis URL and reset connection
        loom.config.settings.redis_url = original_redis_url
        queue_module._redis = None
