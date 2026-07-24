"""Integration tests for version conflict → PendingBranch creation.

Tests cover:
- PendingBranch record created on version conflict
- Correct version succeeds with no PendingBranch
- PendingBranch has correct fields (context_unit_id, conflict_type, resolution)
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
    p = Project(name="Versioning Test Project")
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


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_branch_created_on_conflict(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A version conflict creates a pending_branches record."""
    # Write a parent unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Parent for conflict test",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # Try to write a child with a stale version
    conflict_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Conflicting child write",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 1,  # stale — parent is version 1, expected child version is 2
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=conflict_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409

    # Verify a PendingBranch was created
    result = await db_session.execute(
        text(
            "SELECT id, context_unit_id, conflict_type, resolution "
            "FROM pending_branches ORDER BY created_at DESC LIMIT 1"
        ),
    )
    branch = result.one_or_none()
    assert branch is not None, "Expected a pending_branches record"
    assert str(branch.context_unit_id) == parent_id
    assert branch.conflict_type == "version_conflict"
    assert branch.resolution == "pending"


@pytest.mark.asyncio
async def test_no_pending_branch_on_successful_write(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A successful write with correct version does NOT create a PendingBranch."""
    # Write parent
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Parent for success test",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # Write child with correct version (parent is v1, expected child = v2)
    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Child with correct version",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,  # correct: max(parent.version) + 1
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    # Verify NO PendingBranch was created for this parent
    result = await db_session.execute(
        text(
            "SELECT id FROM pending_branches "
            "WHERE context_unit_id = :pid ORDER BY created_at DESC"
        ),
        {"pid": parent_id},
    )
    assert result.first() is None, "No PendingBranch should exist for successful writes"


@pytest.mark.asyncio
async def test_multiple_conflicts_create_multiple_branches(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Multiple agents conflicting on the same parent create separate branches."""
    # Write parent unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Hotly contested parent",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    # Two conflicting writes with different client_uuids
    for i in range(2):
        conflict_body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "message",
            "content": f"Conflicting write #{i}",
            "parent_ids": [parent_id],
            "parent_relations": ["derived_from"],
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=conflict_body,
            headers=auth_headers,
        )
        assert resp.status_code == 409

    # Verify two PendingBranches exist for this parent
    result = await db_session.execute(
        text(
            "SELECT id FROM pending_branches "
            "WHERE context_unit_id = :pid ORDER BY created_at"
        ),
        {"pid": parent_id},
    )
    branches = result.all()
    assert len(branches) == 2, "Expected two PendingBranch records"


@pytest.mark.asyncio
async def test_conflict_response_has_all_structured_fields(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """409 response includes current_version, claimed_version, pending_branch_id."""
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Parent for field check",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    parent_id = resp.json()["id"]

    conflict_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Field check conflict",
        "parent_ids": [parent_id],
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=conflict_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"] == "VERSION_CONFLICT"
    assert data["claimed_version"] == 1
    assert data["current_version"] == 1  # parent is version 1
    assert "pending_branch_id" in data
    uuid.UUID(data["pending_branch_id"])
    assert "context_unit_id" in data
    assert data["context_unit_id"] == parent_id
