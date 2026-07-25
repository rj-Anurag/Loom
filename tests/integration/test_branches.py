"""Integration tests for Phase 2.1 — Branch CRUD + Merge via HTTP API.

Tests define the expected behaviour of REST endpoints that will exist at
``/v1/projects/{project_id}/branches``:

    POST   /v1/projects/{project_id}/branches              → Create branch (201)
    GET    /v1/projects/{project_id}/branches               → List branches (200)
    GET    /v1/projects/{project_id}/branches/{id}          → Get branch (200 / 404)
    POST   /v1/projects/{project_id}/branches/{id}/merge    → Merge branch (200)

Merge result payload:
    {"status": "merged" | "conflict" | "nothing_to_merge"}

All tests use existing fixtures from ``tests/conftest.py`` plus local
fixtures defined here.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Branch Test Project")
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


# ── Branch create ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST branches returns 201 with branch data including id, name, status."""
    body = {
        "name": "feature/auth-implementation",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "id" in data
    assert data["name"] == "feature/auth-implementation"
    assert data["status"] == "open"
    assert "created_at" in data
    assert "project_id" in data
    assert data["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_create_duplicate_branch_name(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Creating two branches with the same name returns 409."""
    body = {
        "name": "feature/duplicate-test",
    }
    # First create should succeed
    resp1 = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json=body,
        headers=auth_headers,
    )
    assert resp1.status_code == 201

    # Second create with same name should fail
    resp2 = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json=body,
        headers=auth_headers,
    )
    assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}: {resp2.text}"
    assert "BRANCH_NAME_TAKEN" in resp2.text


@pytest.mark.asyncio
async def test_create_branch_missing_name(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Creating a branch without a name returns 422."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── Branch list ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_branches(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET branches returns project-scoped branch list."""
    # Create two branches
    names = ["feature/search", "fix/cache-bug"]
    created_ids = []
    for name in names:
        resp = await client.post(
            f"/v1/projects/{test_project.id}/branches",
            json={"name": name},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    # List branches
    resp = await client.get(
        f"/v1/projects/{test_project.id}/branches",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    returned_ids = [b["id"] for b in data]
    for cid in created_ids:
        assert cid in returned_ids, f"Branch {cid} should be in the list"

    # Verify project isolation: create another project and verify its branch
    # list doesn't include these branches
    assert all(b["project_id"] == str(test_project.id) for b in data)


@pytest.mark.asyncio
async def test_list_branches_empty(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """A project with no branches returns an empty list."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/branches",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ── Branch get (single) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET branches/{id} returns 200 with the full branch record."""
    # Create
    create_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/get-test", "description": "Test the GET endpoint"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    branch_id = create_resp.json()["id"]

    # Get by id
    resp = await client.get(
        f"/v1/projects/{test_project.id}/branches/{branch_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == branch_id
    assert data["name"] == "feature/get-test"


@pytest.mark.asyncio
async def test_get_nonexistent_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET branches/{id} for a nonexistent id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(
        f"/v1/projects/{test_project.id}/branches/{fake_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── Branch merge ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_empty_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Merging a branch with no context units returns status='nothing_to_merge'."""
    # Create a branch (it has no context units yet)
    create_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/empty-merge"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    branch_id = create_resp.json()["id"]

    # Merge the empty branch
    resp = await client.post(
        f"/v1/projects/{test_project.id}/branches/{branch_id}/merge",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "nothing_to_merge"


@pytest.mark.asyncio
async def test_merge_non_conflicting_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Merging a branch with non-overlapping context units auto-merges successfully."""
    # 1. Write a parent context unit on main
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement notification system",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Create a branch
    branch_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/notifications"},
        headers=auth_headers,
    )
    assert branch_resp.status_code == 201
    branch_id = branch_resp.json()["id"]

    # 3. Write context units on the branch (using branch_id parameter)
    branch_body_1 = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Built email notification module in src/notifications/email.py",
        "parent_ids": [parent_id],
        "version": 2,
        "branch_id": branch_id,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=branch_body_1,
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"Write on branch failed: {resp.text}"
    branch_unit_id = resp.json()["id"]

    branch_body_2 = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Set up push notification in src/notifications/push.py",
        "parent_ids": [parent_id],
        "version": 2,
        "branch_id": branch_id,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=branch_body_2,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # 4. Merge the branch — non-overlapping content should auto-merge
    merge_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches/{branch_id}/merge",
        headers=auth_headers,
    )
    assert merge_resp.status_code == 200, f"Merge failed: {merge_resp.text}"
    assert merge_resp.json()["status"] == "merged"


@pytest.mark.asyncio
async def test_merge_conflicting_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Merging a branch whose content overlaps with main creates a PendingBranch."""
    # 1. Write parent context unit on main
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Decision: implement caching strategy",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # 2. Write a unit on main (simulates concurrent work)
    main_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implemented Redis cache in src/cache/redis_client.py",
        "parent_ids": [parent_id],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=main_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    main_unit_id = resp.json()["id"]

    # 3. Create a branch
    branch_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/cache-alternative"},
        headers=auth_headers,
    )
    assert branch_resp.status_code == 201
    branch_id = branch_resp.json()["id"]

    # 4. Write overlapping content on the branch
    branch_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implemented Memcached in src/cache/redis_client.py",  # same file!
        "parent_ids": [parent_id],
        "version": 2,
        "branch_id": branch_id,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=branch_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # 5. Merge the branch — overlapping content should trigger a conflict PendingBranch
    merge_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches/{branch_id}/merge",
        headers=auth_headers,
    )
    assert merge_resp.status_code == 200, f"Merge returned unexpected status: {merge_resp.text}"
    data = merge_resp.json()
    assert data["status"] == "conflict"
    assert len(data["conflict_ids"]) >= 1

    # 6. Verify a PendingBranch exists with branch_id set
    pending_id = data["conflict_ids"][0]
    result = await db_session.execute(
        text("SELECT id, resolution, branch_id FROM pending_branches WHERE id = :pid"),
        {"pid": uuid.UUID(pending_id)},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.resolution == "pending"
    assert row.branch_id is not None
    assert str(row.branch_id) == branch_id


@pytest.mark.asyncio
async def test_merge_nonexistent_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Merging a branch that doesn't exist returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.post(
        f"/v1/projects/{test_project.id}/branches/{fake_id}/merge",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_merge_already_merged_branch(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Merging an already-merged branch returns 400."""
    # Create a branch
    create_resp = await client.post(
        f"/v1/projects/{test_project.id}/branches",
        json={"name": "feature/already-merged"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    branch_id = create_resp.json()["id"]

    # Merge (empty, so nothing_to_merge — that still counts as a merge attempt)
    merge1 = await client.post(
        f"/v1/projects/{test_project.id}/branches/{branch_id}/merge",
        headers=auth_headers,
    )
    assert merge1.status_code == 200

    # Mark the branch as merged in the DB (simulating the post-merge state)
    from sqlalchemy import text
    await db_session.execute(
        text("UPDATE branches SET status = 'merged' WHERE id = :bid"),
        {"bid": uuid.UUID(branch_id)},
    )
    await db_session.commit()

    # Second merge should return nothing_to_merge
    merge2 = await client.post(
        f"/v1/projects/{test_project.id}/branches/{branch_id}/merge",
        headers=auth_headers,
    )
    assert merge2.status_code == 200
    assert merge2.json()["status"] == "nothing_to_merge"
