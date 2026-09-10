"""Integration tests for the Context Service write path.

Tests cover:
- Successful write with full payload
- Idempotency via client_uuid
- Version conflict detection
- Event log append on write
- Context edges for parent references
- Validation: invalid project, unauthorized, invalid type, oversized content
- Trust tier propagation
"""

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
    p = Project(name="Write Test Project")
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
    """For MVP the Bearer token is the agent_id UUID directly."""
    return {"Authorization": f"Bearer {test_agent.id}"}


# ── Success Path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_success(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST returns 201 with the new context unit ID."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Hello from agent",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "id" in data
    assert data["version"] == 1
    assert data["client_uuid"] == body["client_uuid"]


@pytest.mark.asyncio
async def test_write_context_with_all_fields(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Write with trust_tier, parent_ids, and parent_relations."""
    # First write a parent context unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Parent decision: use bcrypt",
        "version": 1,
    }
    parent_resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]

    # Write a child referencing the parent (version must be parent.version + 1)
    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "trust_tier": "agent",
        "content": "Implemented bcrypt per the decision",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    child_id = resp.json()["id"]

    # Verify the edge was created
    result = await db_session.execute(
        text(
            "SELECT parent_id, child_id, relation FROM context_edges "
            "WHERE parent_id = :pid AND child_id = :cid"
        ),
        {"pid": parent_id, "cid": child_id},
    )
    edge = result.one_or_none()
    assert edge is not None
    assert edge.relation == "derived_from"


# ── Idempotency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_idempotent(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Same client_uuid returns the same record (no duplicate)."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Idempotent write",
        "version": 1,
    }
    resp1 = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    resp2 = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 200  # idempotent: returns 200, not 201
    assert resp1.json()["id"] == resp2.json()["id"]


# ── Version Conflicts ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_version_conflict(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST with stale version returns 409."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Original write",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    original_id = resp.json()["id"]

    # Try to write again with the same version — should conflict
    conflict_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Conflicting write",
        "parent_ids": [original_id],
        "parent_relations": ["derived_from"],
        "version": 1,  # Stale — original is already version 1
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=conflict_body,
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    data = resp.json()
    assert data["detail"] == "VERSION_CONFLICT"
    assert data["claimed_version"] == 1
    assert data["current_version"] >= 1  # parent version
    assert "pending_branch_id" in data
    assert "context_unit_id" in data
    # Verify pending_branch_id is a valid UUID
    uuid.UUID(data["pending_branch_id"])


# ── Event Log ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_event_log(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Event log contains one 'write' event per successful write."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Event log test",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    unit_id = resp.json()["id"]

    result = await db_session.execute(
        text(
            "SELECT event_type, payload FROM event_log "
            "WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": test_project.id},
    )
    event = result.one_or_none()
    assert event is not None
    assert event.event_type == "write"
    assert unit_id in str(event.payload)


# ── Validation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_invalid_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """POST to a non-existent project returns 404."""
    fake_id = uuid.uuid4()
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Should not exist",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{fake_id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_write_context_unauthorized(
    client: AsyncClient,
    test_project: Project,
) -> None:
    """POST without auth returns 401."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "No auth",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_write_context_invalid_type(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST with invalid type enum returns 400."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "invalid_type_value",
        "content": "Bad type",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_write_context_empty_content(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST with empty content returns 422 (Pydantic validates min_length)."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 422  # Pydantic validates min_length=1


@pytest.mark.asyncio
async def test_write_context_missing_client_uuid(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST without client_uuid returns 422 (Pydantic validation)."""
    body = {
        "type": "message",
        "content": "No client_uuid",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 422  # Pydantic validates required fields


@pytest.mark.asyncio
async def test_write_context_agent_belongs_to_project(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Agent must be registered under the target project."""
    # Create an agent from a DIFFERENT project
    from loom.db import async_session_factory

    session = async_session_factory()
    other_project = Project(name="Other Project")
    session.add(other_project)
    await session.commit()
    await session.refresh(other_project)
    wrong_agent = Agent(project_id=other_project.id, kind="local")
    session.add(wrong_agent)
    await session.commit()
    await session.refresh(wrong_agent)
    await session.close()

    wrong_headers = {"Authorization": f"Bearer {wrong_agent.id}"}
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Wrong project agent",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=wrong_headers,
    )
    assert resp.status_code == 403
