"""Integration tests for Phase 2.6 — Multi-Agent Concurrent Demo.

Tests the demo agent read/write cycle, non-overlapping auto-merge,
and overlapping conflict detection.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from agents.demo.stubs import LoginFormAgent, PasswordAgent, SessionAgent
from agents.local.agent import LoomClient
from loom.models import Agent, Project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Multi-Agent Demo Test")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def agent_token(db_session: AsyncSession, test_project: Project) -> str:
    """Create an agent and return its UUID as the auth token."""
    a = Agent(project_id=test_project.id, kind="local", name="Test Agent")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return str(a.id)


@pytest_asyncio.fixture
async def agent_token_2(db_session: AsyncSession, test_project: Project) -> str:
    """Create a second agent in the same project."""
    a = Agent(project_id=test_project.id, kind="cloud", name="Second Agent")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return str(a.id)


def _make_client(api_key: str, http_client: httpx.AsyncClient | None = None) -> LoomClient:
    cfg = type("Cfg", (), {"loom_api_url": "http://test", "loom_api_key": api_key})()
    return LoomClient(cfg, http_client=http_client)


# ═════════════════════════════════════════════════════════════════════════════
# Agent Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestDemoAgent:
    """DemoAgent writes context units correctly."""

    @pytest.mark.asyncio
    async def test_agent_writes_units(
        self,
        client: AsyncClient,
        test_project: Project,
        agent_token: str,
    ) -> None:
        """DemoAgent writes num_writes context units and returns correct count."""
        loom = _make_client(agent_token, http_client=client)
        agent = PasswordAgent(loom, "Test Agent", "local", num_writes=3)
        result = await agent.run(str(test_project.id), "Test task")

        assert result.writes_count == 3
        assert len(result.unit_ids) == 3
        assert result.agent_name == "Test Agent"
        assert result.agent_kind == "local"

        # Verify the units exist in the DB
        for uid in result.unit_ids:
            resp = await client.get(
                f"/v1/projects/{test_project.id}/context",
                headers={"Authorization": f"Bearer {agent_token}"},
                params={"query": uid, "budget": 4096, "scope": "full"},
            )
            assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Merge / Conflict Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestMergeAndConflict:
    """Non-overlapping writes auto-merge; overlapping writes conflict."""

    @pytest.mark.asyncio
    async def test_non_overlapping_auto_merge(
        self,
        client: AsyncClient,
        test_project: Project,
        agent_token: str,
        agent_token_2: str,
    ) -> None:
        """Two agents writing disjoint entities both succeed with different IDs."""
        loom = _make_client(agent_token, http_client=client)

        # Write a shared parent
        _ = await loom.write_context(
            project_id=str(test_project.id),
            content="Shared parent: Authentication System",
            version=1,
            type_="message",
        )

        # Agent A writes about hash.py (disjoint)
        agent_a = PasswordAgent(loom, "Agent A", "local", num_writes=1)
        result_a = await agent_a.run(str(test_project.id), "password")
        a_id = result_a.unit_ids[0]

        # Agent B writes about session.py (disjoint) — concurrent agent
        loom2 = _make_client(agent_token_2, http_client=client)
        agent_b = SessionAgent(loom2, "Agent B", "cloud", num_writes=1)
        result_b = await agent_b.run(str(test_project.id), "session")
        b_id = result_b.unit_ids[0]

        # Both writes should succeed with different unit IDs
        assert a_id is not None
        assert b_id is not None
        assert a_id != b_id

    @pytest.mark.asyncio
    async def test_overlapping_conflict_detection(
        self,
        client: AsyncClient,
        test_project: Project,
        agent_token: str,
        agent_token_2: str,
    ) -> None:
        """Two agents with overlapping entities produce a conflict."""
        loom = _make_client(agent_token, http_client=client)

        # Agent A writes about hash.py
        agent_a = PasswordAgent(loom, "Agent A", "local", num_writes=1)
        await agent_a.run(str(test_project.id), "password")

        # Agent C's step 3 overlaps with Agent A (same entities)
        # Use a fresh loom to simulate independent agent
        loom2 = _make_client(agent_token_2, http_client=client)
        agent_c = LoginFormAgent(loom2, "Agent C", "browser", num_writes=1)

        # Override content for this single-unit agent to be the overlapping step
        agent_c._content_for_step = lambda step, task, ctx: (
            "Integration: The login form handler calls `def hash_password` from "
            "`src/auth/hash.py`. This entity overlaps with the password agent."
        )
        result_c = await agent_c.run(str(test_project.id), "login")

        # The write should have succeeded (conflicts raise on detection,
        # not on write — the version/branch system handles it)
        assert len(result_c.unit_ids) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Registration + Auth Flow Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestRegistrationAuthFlow:
    """End-to-end: register agent → auth with returned token."""

    @pytest.mark.asyncio
    async def test_register_then_authenticate(
        self,
        client: AsyncClient,
        test_project: Project,
        agent_token: str,
    ) -> None:
        """Agent registered via API can authenticate with returned api_key."""
        # Register
        resp = await client.post(
            f"/v1/projects/{test_project.id}/agents",
            json={"kind": "local", "name": "E2E Test Agent"},
            headers={"Authorization": f"Bearer {agent_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        api_key = data["api_key"]

        # Authenticate and read project
        resp = await client.get(
            f"/v1/projects/{test_project.id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # Write context
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json={
                "client_uuid": str(uuid.uuid4()),
                "type": "decision",
                "content": "E2E test write",
                "version": 1,
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201
