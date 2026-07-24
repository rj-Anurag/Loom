"""Integration tests for the Event Log (append-only ledger).

Tests cover:
- Enriched write payload (trust_tier, content_preview, parent_ids, etc.)
- Content hash (SHA-256 of content) in event payload
- Event log is queryable by project_id in chronological order
- Projection rebuild from event log
"""

import hashlib
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
    p = Project(name="Event Log Test")
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


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_payload_enriched(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Write event payload includes trust_tier, content_preview, parent_ids, etc."""
    # First write a parent unit
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Parent: use Redis for caching",
        "version": 1,
    }
    parent_resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]

    # Write a child with all fields
    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "trust_tier": "agent",
        "content": "Implemented Redis caching layer with connection pooling and retry logic",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Fetch the event log entry
    result = await db_session.execute(
        text(
            "SELECT payload FROM event_log "
            "WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": test_project.id},
    )
    row = result.one_or_none()
    assert row is not None
    payload = row.payload

    # Verify enriched fields
    assert "trust_tier" in payload
    assert payload["trust_tier"] == "agent"
    assert "content_preview" in payload
    assert len(payload["content_preview"]) <= 200
    assert "parent_ids" in payload
    assert len(payload["parent_ids"]) == 1
    assert payload["parent_ids"][0] == parent_id
    assert "parent_relations" in payload
    assert payload["parent_relations"] == ["derived_from"]
    assert "version" in payload
    assert payload["version"] == 2


@pytest.mark.asyncio
async def test_event_content_hash(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Event payload includes a SHA-256 content_hash of the unit content."""
    content = "Content for hash verification test"
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": content,
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    result = await db_session.execute(
        text(
            "SELECT payload FROM event_log "
            "WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": test_project.id},
    )
    row = result.one_or_none()
    assert row is not None
    payload = row.payload

    assert "content_hash" in payload
    expected_hash = hashlib.sha256(content.encode()).hexdigest()
    assert payload["content_hash"] == expected_hash


@pytest.mark.asyncio
async def test_event_log_chronological(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Event log returns entries in chronological order (oldest first)."""
    # Write two units sequentially
    body1 = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "First event",
        "version": 1,
    }
    await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body1,
        headers=auth_headers,
    )

    body2 = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Second event",
        "version": 1,
    }
    await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body2,
        headers=auth_headers,
    )

    # Query events in order
    result = await db_session.execute(
        text(
            "SELECT event_type, payload->>'type' AS unit_type, created_at "
            "FROM event_log "
            "WHERE project_id = :pid "
            "ORDER BY created_at ASC"
        ),
        {"pid": test_project.id},
    )
    rows = result.all()
    event_log_types = [r.unit_type for r in rows if r.event_type == "write"]

    # The last two writes should be in order: message then decision
    assert event_log_types[-2:] == ["message", "decision"]


@pytest.mark.asyncio
async def test_event_log_default_content_preview(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """content_preview is truncated to 200 chars for long content."""
    long_content = "A" * 500
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": long_content,
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201

    result = await db_session.execute(
        text(
            "SELECT payload FROM event_log "
            "WHERE project_id = :pid ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": test_project.id},
    )
    row = result.one_or_none()
    assert row is not None
    assert len(row.payload["content_preview"]) == 200


# ── Rebuild from Event Log ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rebuild_reconstructs_graph(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Rebuilding projections from the event log reconstructs the graph."""
    # Write two related units
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Parent decision",
        "version": 1,
    }
    parent_resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]

    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Child result",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,
    }
    child_resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )
    child_id = child_resp.json()["id"]

    # Snapshot the expected state
    units_before = await db_session.execute(
        text("SELECT id, type, content, version FROM context_units WHERE project_id = :pid ORDER BY created_at"),
        {"pid": test_project.id},
    )
    expected_units = {(str(r.id), r.type, r.content, r.version) for r in units_before.all()}

    edges_before = await db_session.execute(
        text("SELECT parent_id, child_id, relation FROM context_edges"),
    )
    expected_edges = {(str(r.parent_id), str(r.child_id), r.relation) for r in edges_before.all()}

    # Delete project-scoped data (edges first, then units)
    await db_session.execute(
        text(
            "DELETE FROM context_edges WHERE child_id IN "
            "(SELECT id FROM context_units WHERE project_id = :pid)"
        ),
        {"pid": test_project.id},
    )
    await db_session.execute(
        text("DELETE FROM context_units WHERE project_id = :pid"),
        {"pid": test_project.id},
    )
    await db_session.commit()

    # Verify they're gone
    count = await db_session.execute(
        text("SELECT COUNT(*) FROM context_units WHERE project_id = :pid"),
        {"pid": test_project.id},
    )
    assert count.scalar() == 0

    # Rebuild from event log
    from loom.services.context.service import rebuild_projections

    await rebuild_projections(db_session, test_project.id)
    await db_session.commit()

    # Verify rebuilt state matches original
    units_after = await db_session.execute(
        text("SELECT id, type, content, version FROM context_units WHERE project_id = :pid ORDER BY created_at"),
        {"pid": test_project.id},
    )
    rebuilt_units = {(str(r.id), r.type, r.content, r.version) for r in units_after.all()}
    assert rebuilt_units == expected_units, f"Expected {expected_units}, got {rebuilt_units}"

    edges_after = await db_session.execute(
        text("SELECT parent_id, child_id, relation FROM context_edges"),
    )
    rebuilt_edges = {(str(r.parent_id), str(r.child_id), r.relation) for r in edges_after.all()}
    assert rebuilt_edges == expected_edges, f"Expected {expected_edges}, got {rebuilt_edges}"
