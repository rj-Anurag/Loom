"""Integration tests for Phase 2.4 — Redis Live Presence API.

Tests the heartbeat endpoint and presence query endpoint through
the FastAPI app.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import redis.asyncio as redis_async
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Presence Test Project")
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


# ── Heartbeat Tests ───────────────────────────────────────────────────────────


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


# ── Presence Query Tests ─────────────────────────────────────────────────────


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


@pytest.mark.asyncio
async def test_presence_query_cross_project_blocked(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """Presence query for a different project returns 403."""
    import uuid

    other_project_id = uuid.uuid4()
    resp = await client.get(
        f"/v1/projects/{other_project_id}/agents/presence",
        headers=auth_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "PROJECT_MISMATCH"
