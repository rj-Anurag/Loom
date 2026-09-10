"""Integration tests for trust-tier field enforcement.

Tests cover:
- Default trust_tier is 'agent' when not specified
- Agent (kind=local) cannot write at 'user' tier
- Agent can write at 'agent' tier
- Agent can write at 'external_tool' tier
- Error message for denied trust tier is descriptive
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
    p = Project(name="Trust Tier Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    """A standard local agent (default kind='local')."""
    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def browser_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    """A browser agent (represents a human user)."""
    a = Agent(project_id=test_project.id, kind="browser")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def auth_headers(test_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_agent.id}"}


@pytest_asyncio.fixture
async def browser_auth_headers(browser_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {browser_agent.id}"}


# ── Default ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_trust_tier_is_agent(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Write without trust_tier defaults to 'agent' in the DB."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Default trust tier test",
        "version": 1,
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201
    unit_id = resp.json()["id"]

    # Verify the DB has 'agent' as the trust_tier
    result = await db_session.execute(
        text("SELECT trust_tier FROM context_units WHERE id = :uid"),
        {"uid": unit_id},
    )
    row = result.one_or_none()
    assert row is not None
    assert row.trust_tier == "agent"


# ── Enforcement: local agent ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_agent_cannot_write_user_tier(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """A local agent writing at 'user' trust tier gets 403."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Attempt to write at user tier",
        "version": 1,
        "trust_tier": "user",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    assert "TRUST_TIER_DENIED" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_local_agent_can_write_agent_tier(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """A local agent can explicitly write at 'agent' tier."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Writing at agent tier",
        "version": 1,
        "trust_tier": "agent",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] is not None


@pytest.mark.asyncio
async def test_local_agent_can_write_external_tool_tier(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """A local agent can write at 'external_tool' tier."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "External tool report",
        "version": 1,
        "trust_tier": "external_tool",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


# ── Browser agent can write at user tier ──────────────────────────────────────


@pytest.mark.asyncio
async def test_browser_agent_can_write_user_tier(
    client: AsyncClient,
    test_project: Project,
    browser_auth_headers: dict[str, str],
) -> None:
    """A browser agent (representing a human) CAN write at 'user' tier."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "message",
        "content": "Human user message via browser extension",
        "version": 1,
        "trust_tier": "user",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=browser_auth_headers,
    )
    assert resp.status_code == 201, resp.text


# ── Trust tier is preserved through write-read cycle ──────────────────────────


@pytest.mark.asyncio
async def test_trust_tier_preserved_in_read(
    client: AsyncClient,
    test_project: Project,
    browser_auth_headers: dict[str, str],
) -> None:
    """Trust tier written as 'user' comes back as 'user' in reads."""
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "User-approved architecture decision",
        "version": 1,
        "trust_tier": "user",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=body,
        headers=browser_auth_headers,
    )
    assert resp.status_code == 201
    unit_id = resp.json()["id"]

    # Read it back
    read_resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        headers=browser_auth_headers,
    )
    assert read_resp.status_code == 200
    units = read_resp.json()["units"]
    matching = [u for u in units if u["id"] == unit_id]
    assert len(matching) == 1
    assert matching[0]["trust_tier"] == "user"
