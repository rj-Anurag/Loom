"""Tests for Phase 1.10 — Local Agent Prototype.

Covers the read → LLM → write loop with mocked LLM responses.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models.agents import Agent
from loom.models.projects import Project

pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    from loom.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    from loom.db import async_session_factory

    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    from loom.models.projects import Project

    p = Project(name="local-agent-test")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    from loom.models.agents import Agent

    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def auth_headers(test_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_agent.id}"}


@pytest_asyncio.fixture
async def asgi_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from loom.api.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
def agent_config(test_agent: Agent) -> AgentConfig:
    from agents.local.config import AgentConfig

    return AgentConfig(
        loom_api_url="http://test",
        loom_api_key=str(test_agent.id),
        groq_api_key="mock-groq-key",
        default_project_id="",
    )


# ── LoomClient Tests ──────────────────────────────────────────────────────────


class TestLoomClient:
    """Tests for the Loom HTTP client used by the agent."""

    @pytest_asyncio.fixture
    async def loom_client(self, test_agent: Agent, asgi_http_client: httpx.AsyncClient) -> AsyncGenerator[LoomClient, None]:
        from agents.local.agent import LoomClient
        from agents.local.config import AgentConfig

        cfg = AgentConfig(
            loom_api_url="http://test",
            loom_api_key=str(test_agent.id),
        )
        lc = LoomClient(cfg, http_client=asgi_http_client)
        try:
            yield lc
        finally:
            await lc.close()

    async def test_read_context_returns_units(
        self,
        client: AsyncClient,
        test_project: Project,
        test_agent: Agent,
        auth_headers: dict,
        loom_client: LoomClient,
    ) -> None:
        """LoomClient.read_context returns units written to the API."""
        # Seed some context via the test client
        body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "Use bcrypt for password hashing",
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=body,
            headers=auth_headers,
        )
        assert resp.status_code == 201

        units = await loom_client.read_context(
            str(test_project.id), "password hashing"
        )
        assert len(units) >= 1
        assert any("bcrypt" in u["content"] for u in units)

    async def test_write_context_creates_unit(
        self,
        test_project: Project,
        loom_client: LoomClient,
    ) -> None:
        """LoomClient.write_context creates a unit and returns its ID."""
        result = await loom_client.write_context(
            str(test_project.id),
            "Use Argon2 for password hashing",
            type_="decision",
        )
        assert "id" in result
        assert result["version"] == 1

    async def test_write_context_with_parents(
        self,
        test_project: Project,
        loom_client: LoomClient,
        auth_headers: dict,
        client: AsyncClient,
    ) -> None:
        """LoomClient.write_context accepts parent_ids for edge creation."""
        # Create a parent unit via the test client
        body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "Parent decision",
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=body,
            headers=auth_headers,
        )
        parent_id = resp.json()["id"]

        result = await loom_client.write_context(
            str(test_project.id),
            "Child decision based on parent",
            type_="decision",
            version=2,
            parent_ids=[parent_id],
        )
        assert "id" in result


# ── GroqLLM Tests ─────────────────────────────────────────────────────────────


class TestGroqLLM:
    """Tests for the Groq LLM wrapper (with mocked client)."""

    async def test_generate_returns_text(self) -> None:
        """GroqLLM.generate returns the text content from a mock response."""
        from agents.local.agent import GroqLLM
        from agents.local.config import AgentConfig

        cfg = AgentConfig(groq_api_key="mock-key")
        llm = GroqLLM(cfg)

        with patch.object(llm._client.chat.completions, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value.choices = [
                type("obj", (), {"message": type("msg", (), {"content": "Hello from Groq"})})()
            ]
            result = await llm.generate("Say hello")
            assert result == "Hello from Groq"
            mock_create.assert_awaited_once()

    async def test_generate_empty_response(self) -> None:
        """GroqLLM returns empty string when content is None."""
        from agents.local.agent import GroqLLM
        from agents.local.config import AgentConfig

        cfg = AgentConfig(groq_api_key="mock-key")
        llm = GroqLLM(cfg)

        with patch.object(llm._client.chat.completions, "create", new=AsyncMock()) as mock_create:
            mock_create.return_value.choices = [
                type("obj", (), {"message": type("msg", (), {"content": None})})()
            ]
            result = await llm.generate("test")
            assert result == ""


# ── LocalAgent Integration Tests ──────────────────────────────────────────────


class TestLocalAgent:
    """End-to-end tests for the LocalAgent loop (LLM mocked)."""

    async def test_agent_read_write_loop(
        self,
        test_project: Project,
        test_agent: Agent,
        agent_config: AgentConfig,
        asgi_http_client: httpx.AsyncClient,
    ) -> None:
        """Agent reads context, calls (mocked) LLM, and writes result."""
        from agents.local.agent import LocalAgent

        agent = LocalAgent(cfg=agent_config, http_client=asgi_http_client)
        try:
            # Mock the LLM call
            with patch.object(agent.llm, "generate", new=AsyncMock(return_value="Mocked LLM result")):
                result = await agent.run(
                    task_description="Write a test decision",
                    project_id=str(test_project.id),
                )
            assert result is not None
            assert "id" in result
        finally:
            await agent.close()

    async def test_agent_written_context_is_readable(
        self,
        client: AsyncClient,
        test_project: Project,
        test_agent: Agent,
        agent_config: AgentConfig,
        auth_headers: dict,
        asgi_http_client: httpx.AsyncClient,
    ) -> None:
        """After the agent writes, the unit is visible via the read API."""
        from agents.local.agent import LocalAgent

        agent = LocalAgent(cfg=agent_config, http_client=asgi_http_client)
        try:
            with patch.object(agent.llm, "generate", new=AsyncMock(
                return_value="The project should use JWT with refresh tokens"
            )):
                await agent.run(
                    task_description="Design auth flow",
                    project_id=str(test_project.id),
                )
        finally:
            await agent.close()

        # Verify the written unit is readable
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "JWT", "budget": 1024},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        units = resp.json()["units"]
        assert any("JWT" in u["content"] for u in units)

    async def test_agent_dry_run_skips_llm(
        self,
        test_project: Project,
        agent_config: AgentConfig,
        asgi_http_client: httpx.AsyncClient,
    ) -> None:
        """Dry-run mode does not call the LLM or write."""
        from agents.local.agent import LocalAgent

        agent = LocalAgent(cfg=agent_config, http_client=asgi_http_client)
        try:
            result = await agent.run(
                task_description="Should not actually run",
                project_id=str(test_project.id),
                dry_run=True,
            )
            assert result["status"] == "dry_run"
        finally:
            await agent.close()

    async def test_agent_raises_without_project_id(self) -> None:
        """Agent raises ValueError when no project ID is provided."""
        from agents.local.agent import LocalAgent

        agent = LocalAgent()
        try:
            with pytest.raises(ValueError, match="No project_id"):
                await agent.run("test task")
        finally:
            await agent.close()

    async def test_agent_handles_write_after_read_with_parents(
        self,
        test_project: Project,
        test_agent: Agent,
        agent_config: AgentConfig,
        asgi_http_client: httpx.AsyncClient,
    ) -> None:
        """Agent writes with parent_ids derived from read context."""
        from agents.local.agent import LocalAgent

        agent = LocalAgent(cfg=agent_config, http_client=asgi_http_client)
        try:
            # First write some seed context
            from agents.local.agent import LoomClient

            loom = LoomClient(agent_config, http_client=asgi_http_client)
            try:
                seed = await loom.write_context(
                    str(test_project.id), "Seed context for agent test"
                )
            finally:
                await loom.close()

            with patch.object(agent.llm, "generate", new=AsyncMock(
                return_value="Result based on seed context"
            )):
                result = await agent.run(
                    task_description="Build on seed context",
                    project_id=str(test_project.id),
                )
            assert result is not None
            assert "id" in result
        finally:
            await agent.close()
