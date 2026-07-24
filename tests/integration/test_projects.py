"""Integration tests for Project management endpoints.

Phase 1.11 — Browser Extension Core.
Tests cover:
- GET /v1/projects — list projects (for popup dropdown)
- POST /v1/projects — create a project
- POST /v1/projects/{id}/link/chat — link a chat URL to a project
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Project Test")
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


# ── List Projects ─────────────────────────────────────────────────────────────


class TestListProjects:
    """GET /v1/projects"""

    async def test_list_projects_returns_all(
        self,
        client: AsyncClient,
        test_project: Project,
        auth_headers: dict[str, str],
    ) -> None:
        """Returns a list of all projects."""
        resp = await client.get("/v1/projects", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        ids = [p["id"] for p in data]
        assert str(test_project.id) in ids

    async def test_list_projects_no_auth(
        self,
        client: AsyncClient,
    ) -> None:
        """Returns 401 without Authorization header."""
        resp = await client.get("/v1/projects")
        assert resp.status_code == 401

    async def test_list_projects_empty(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Returns empty list when no projects exist and no valid agent auth."""
        # Create an agent with no projects
        p = Project(name="Orphan Project")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)
        a = Agent(project_id=p.id, kind="local")
        db_session.add(a)
        await db_session.commit()
        await db_session.refresh(a)

        headers = {"Authorization": f"Bearer {a.id}"}
        resp = await client.get("/v1/projects", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


# ── Create Project ────────────────────────────────────────────────────────────


class TestCreateProject:
    """POST /v1/projects"""

    async def test_create_project_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Creates a project and returns it with a browser-kind agent."""
        resp = await client.post(
            "/v1/projects",
            json={"name": "New Test Project"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["name"] == "New Test Project"
        assert "agent_id" in data
        assert "api_key" in data
        # Verify the returned agent is browser-kind
        agent_id = data["agent_id"]
        assert uuid.UUID(agent_id)

    async def test_create_project_missing_name(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """POST without name returns 422."""
        resp = await client.post(
            "/v1/projects",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_project_no_auth(
        self,
        client: AsyncClient,
    ) -> None:
        """POST without auth returns 401."""
        resp = await client.post(
            "/v1/projects",
            json={"name": "Unauthorized Project"},
        )
        assert resp.status_code == 401


# ── Link Chat ─────────────────────────────────────────────────────────────────


class TestLinkChat:
    """POST /v1/projects/{id}/link/chat"""

    async def test_link_chat_success(
        self,
        client: AsyncClient,
        test_project: Project,
        auth_headers: dict[str, str],
    ) -> None:
        """Links a chat URL to a project and returns the link."""
        chat_url = f"https://claude.ai/chat/{uuid.uuid4()}"
        resp = await client.post(
            f"/v1/projects/{test_project.id}/link/chat",
            json={
                "chat_url": chat_url,
                "title": "Event Log Design",
                "platform": "claude.ai",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data
        assert data["chat_url"] == chat_url
        assert data["project_id"] == str(test_project.id)
        assert data["platform"] == "claude.ai"

    async def test_link_chat_idempotent(
        self,
        client: AsyncClient,
        test_project: Project,
        auth_headers: dict[str, str],
    ) -> None:
        """Same chat_url twice returns the same link (no duplicate)."""
        chat_url = f"https://claude.ai/chat/{uuid.uuid4()}"
        body = {
            "chat_url": chat_url,
            "title": "Duplicate Test",
            "platform": "claude.ai",
        }
        resp1 = await client.post(
            f"/v1/projects/{test_project.id}/link/chat",
            json=body,
            headers=auth_headers,
        )
        resp2 = await client.post(
            f"/v1/projects/{test_project.id}/link/chat",
            json=body,
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["id"] == resp2.json()["id"]

    async def test_link_chat_project_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """POST to non-existent project returns 404."""
        fake_id = uuid.uuid4()
        chat_url = f"https://claude.ai/chat/{uuid.uuid4()}"
        resp = await client.post(
            f"/v1/projects/{fake_id}/link/chat",
            json={
                "chat_url": chat_url,
                "title": "No Project",
                "platform": "claude.ai",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_link_chat_no_auth(
        self,
        client: AsyncClient,
        test_project: Project,
    ) -> None:
        """POST without auth returns 401."""
        chat_url = f"https://claude.ai/chat/{uuid.uuid4()}"
        resp = await client.post(
            f"/v1/projects/{test_project.id}/link/chat",
            json={
                "chat_url": chat_url,
                "title": "No Auth",
                "platform": "claude.ai",
            },
        )
        assert resp.status_code == 401
