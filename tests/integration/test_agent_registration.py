"""Integration tests for agent registration (Phase 2.6).

Tests the ``POST /v1/projects/{project_id}/agents`` endpoint which was
previously a stub returning empty strings.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Agent Registration Test")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ── Registration Tests ────────────────────────────────────────────────────────


class TestAgentRegistration:
    """POST /v1/projects/{project_id}/agents."""

    @pytest.mark.asyncio
    async def test_register_agent_with_name(
        self,
        client: AsyncClient,
        test_project: Project,
    ) -> None:
        """Register an agent with kind + name returns credentials."""
        resp = await client.post(
            f"/v1/projects/{test_project.id}/agents",
            json={"kind": "local", "name": "My Demo Agent"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "agent_id" in data
        assert "api_key" in data
        assert data["kind"] == "local"
        assert data["name"] == "My Demo Agent"
        assert data["agent_id"] == data["api_key"]  # MVP auth convention

        # Verify the returned api_key authenticates API calls
        headers = {"Authorization": f"Bearer {data['api_key']}"}
        resp = await client.get(
            f"/v1/projects/{test_project.id}",
            headers=headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_register_agent_without_name(
        self,
        client: AsyncClient,
        test_project: Project,
    ) -> None:
        """Register an agent without name returns None name."""
        resp = await client.post(
            f"/v1/projects/{test_project.id}/agents",
            json={"kind": "cloud"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "cloud"
        assert data["name"] is None

    @pytest.mark.asyncio
    async def test_register_agent_invalid_kind(
        self,
        client: AsyncClient,
        test_project: Project,
    ) -> None:
        """Invalid kind returns 422."""
        resp = await client.post(
            f"/v1/projects/{test_project.id}/agents",
            json={"kind": "invalid_kind"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_agent_missing_kind(
        self,
        client: AsyncClient,
        test_project: Project,
    ) -> None:
        """Missing kind returns 422."""
        resp = await client.post(
            f"/v1/projects/{test_project.id}/agents",
            json={},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_agent_nonexistent_project(
        self,
        client: AsyncClient,
    ) -> None:
        """Non-existent project returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/v1/projects/{fake_id}/agents",
            json={"kind": "local"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "PROJECT_NOT_FOUND"
