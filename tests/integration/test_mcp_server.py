"""Integration tests for the Loom MCP Server.

Tests the MCP tools against the live API (via ASGI transport).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from loom.models import Agent, Project


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """ASGI-transport client for setting up test fixtures."""
    from loom.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_project(db_session) -> Project:
    p = Project(name="MCP Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session, test_project) -> Agent:
    a = Agent(project_id=test_project.id, kind="local", name="MCP Test Agent")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


# ═════════════════════════════════════════════════════════════════════════════
# MCP Server Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestMCPTools:
    """MCP tools work correctly against the live API."""

    @pytest.mark.asyncio
    async def test_tools_are_registered(self) -> None:
        """MCP server has the expected tools registered."""
        from loom.mcp.server import mcp

        # FastMCP stores tools internally; we can inspect them
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        assert "read_context" in tool_names
        assert "write_context" in tool_names
        assert "get_project_summary" in tool_names

    @pytest.mark.asyncio
    async def test_read_context_no_query_returns_no_results(
        self,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """read_context returns empty for a project with no context."""
        import httpx
        from loom.mcp.server import read_context

        # Set up env for the MCP server
        old_key = os.environ.get("LOOM_API_KEY")
        old_pid = os.environ.get("LOOM_PROJECT_ID")
        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_KEY"] = str(test_agent.id)
        os.environ["LOOM_PROJECT_ID"] = str(test_project.id)
        os.environ["LOOM_API_URL"] = "http://test"

        # We need to mock the httpx call to route through ASGI
        async def _do():
            result = await read_context(query="test query", budget=4096, scope="task")
            return result

        try:
            # Intercept httpx calls
            old_aclient = httpx.AsyncClient

            class MockAsyncClient(old_aclient):
                def __init__(self, **kwargs):
                    from loom.api.main import app
                    super().__init__(transport=ASGITransport(app=app), base_url="http://test")

            httpx.AsyncClient = MockAsyncClient

            result = await _do()
        finally:
            httpx.AsyncClient = old_aclient
            if old_key is None:
                del os.environ["LOOM_API_KEY"]
            else:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid is None:
                del os.environ["LOOM_PROJECT_ID"]
            else:
                os.environ["LOOM_PROJECT_ID"] = old_pid
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

        assert "No relevant context found" in result

    @pytest.mark.asyncio
    async def test_write_and_read_context_roundtrip(
        self,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """Write context via MCP tool, then read it back."""
        import httpx
        from loom.mcp.server import read_context, write_context

        old_key = os.environ.get("LOOM_API_KEY")
        old_pid = os.environ.get("LOOM_PROJECT_ID")
        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_KEY"] = str(test_agent.id)
        os.environ["LOOM_PROJECT_ID"] = str(test_project.id)
        os.environ["LOOM_API_URL"] = "http://test"

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                from loom.api.main import app
                super().__init__(transport=ASGITransport(app=app), base_url="http://test")

        old_aclient = httpx.AsyncClient
        httpx.AsyncClient = MockAsyncClient

        try:
            # Write
            write_result = await write_context(
                content="MCP roundtrip test content",
                type="decision",
                version=1,
            )
            assert "created" in write_result or "idempotent" in write_result

            # Read
            read_result = await read_context(
                query="roundtrip",
                budget=4096,
                scope="task",
            )
            assert "MCP roundtrip test content" in read_result
        finally:
            httpx.AsyncClient = old_aclient
            if old_key is None:
                del os.environ["LOOM_API_KEY"]
            else:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid is None:
                del os.environ["LOOM_PROJECT_ID"]
            else:
                os.environ["LOOM_PROJECT_ID"] = old_pid
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

    @pytest.mark.asyncio
    async def test_get_project_summary(
        self,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """get_project_summary returns project info."""
        import httpx
        from loom.mcp.server import get_project_summary

        old_key = os.environ.get("LOOM_API_KEY")
        old_pid = os.environ.get("LOOM_PROJECT_ID")
        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_KEY"] = str(test_agent.id)
        os.environ["LOOM_PROJECT_ID"] = str(test_project.id)
        os.environ["LOOM_API_URL"] = "http://test"

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                from loom.api.main import app
                super().__init__(transport=ASGITransport(app=app), base_url="http://test")

        old_aclient = httpx.AsyncClient
        httpx.AsyncClient = MockAsyncClient

        try:
            result = await get_project_summary()
            assert test_project.name in result
            assert str(test_project.id) in result
        finally:
            httpx.AsyncClient = old_aclient
            if old_key is None:
                del os.environ["LOOM_API_KEY"]
            else:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid is None:
                del os.environ["LOOM_PROJECT_ID"]
            else:
                os.environ["LOOM_PROJECT_ID"] = old_pid
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

    @pytest.mark.asyncio
    async def test_missing_config_raises_error(self) -> None:
        """MCP server raises helpful error when config is missing."""
        from loom.mcp.server import _check_config

        # Temporarily clear env vars
        old_key = os.environ.pop("LOOM_API_KEY", None)
        old_pid = os.environ.pop("LOOM_PROJECT_ID", None)

        try:
            with pytest.raises(ValueError, match="Missing required"):
                _check_config()
        finally:
            if old_key:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid:
                os.environ["LOOM_PROJECT_ID"] = old_pid
