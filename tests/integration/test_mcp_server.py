"""Integration tests for the Loom MCP Server.

Tests the MCP tools against the live API (via ASGI transport).
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from loom.models import Agent, ContextUnit, Project

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
        assert "list_recent_context" in tool_names
        assert "list_sources" in tool_names

        prompts = await mcp.list_prompts()
        assert any(prompt.name == "loom" for prompt in prompts)

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
        old_source = os.environ.get("LOOM_SOURCE_TYPE")
        old_session = os.environ.get("LOOM_SESSION_ID")
        os.environ["LOOM_API_KEY"] = str(test_agent.id)
        os.environ["LOOM_PROJECT_ID"] = str(test_project.id)
        os.environ["LOOM_API_URL"] = "http://test"
        os.environ["LOOM_SOURCE_TYPE"] = "codex_cli"
        os.environ["LOOM_SESSION_ID"] = "codex-test-session"

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
                type="task_result",
                task_name="MCP roundtrip",
                files_touched=["loom/mcp/server.py"],
                tests=[{"command": "pytest -q", "status": "passed"}],
                blockers=[],
                next_steps=["Read from a later session"],
            )
            assert "created" in write_result or "idempotent" in write_result
            assert "source=codex_cli" in write_result
            assert "session=codex-test-session" in write_result

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
            if old_source is None:
                os.environ.pop("LOOM_SOURCE_TYPE", None)
            else:
                os.environ["LOOM_SOURCE_TYPE"] = old_source
            if old_session is None:
                os.environ.pop("LOOM_SESSION_ID", None)
            else:
                os.environ["LOOM_SESSION_ID"] = old_session

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
            assert "Active agents: 0" in result
            assert "Registered agents" not in result
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
    async def test_visibility_tools_use_http_api_and_report_provenance(
        self,
        test_project: Project,
        test_agent: Agent,
        monkeypatch,
    ) -> None:
        import httpx

        from loom.mcp.server import list_recent_context, list_sources, write_context

        monkeypatch.setenv("LOOM_API_KEY", str(test_agent.id))
        monkeypatch.setenv("LOOM_PROJECT_ID", str(test_project.id))
        monkeypatch.setenv("LOOM_API_URL", "http://test")
        monkeypatch.setenv("LOOM_SOURCE_TYPE", "opencode")
        monkeypatch.setenv("LOOM_SESSION_ID", "visibility-session")

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                from loom.api.main import app

                super().__init__(transport=ASGITransport(app=app), base_url="http://test")

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        write_result = await write_context(
            content="Distinctive visibility result",
            type="decision",
        )
        unit_id = write_result.split()[2]

        recent = await list_recent_context(
            limit=10,
            source_type="opencode",
            source_session_id="visibility-session",
            type="decision",
        )
        assert unit_id in recent
        assert "Distinctive visibility result" in recent
        assert "source=opencode" in recent
        assert "session=visibility-session" in recent

        sources = await list_sources()
        assert "source=opencode" in sources
        assert "identity=visibility-session" in sources
        assert "units=1" in sources

    @pytest.mark.asyncio
    async def test_internal_registry_exposes_visibility_tools(
        self,
        db_session,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        from loom.services.context.mcp_tools import ToolRegistry

        registry = ToolRegistry(db_session, test_project.id, test_agent.id)
        names = {tool["name"] for tool in registry.list_tools()}
        assert {"list_recent_context", "list_sources"} <= names

    @pytest.mark.asyncio
    async def test_write_idempotency_is_scoped_to_mcp_session(
        self,
        test_project: Project,
        test_agent: Agent,
        db_session,
        monkeypatch,
    ) -> None:
        import httpx

        from loom.mcp.server import write_context

        monkeypatch.setenv("LOOM_API_KEY", str(test_agent.id))
        monkeypatch.setenv("LOOM_PROJECT_ID", str(test_project.id))
        monkeypatch.setenv("LOOM_API_URL", "http://test")
        monkeypatch.setenv("LOOM_SOURCE_TYPE", "codex_cli")
        monkeypatch.setenv("LOOM_SESSION_ID", "session-one")

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                from loom.api.main import app

                super().__init__(transport=ASGITransport(app=app), base_url="http://test")

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        content = f"Session idempotency {test_project.id}"
        first = await write_context(content=content, type="decision")
        replay = await write_context(content=content, type="decision")
        monkeypatch.setenv("LOOM_SESSION_ID", "session-two")
        second_session = await write_context(content=content, type="decision")

        assert "created" in first
        assert "idempotent replay" in replay
        assert "created" in second_session
        count = await db_session.scalar(
            select(func.count()).select_from(ContextUnit).where(ContextUnit.content == content)
        )
        assert count == 2

    @pytest.mark.asyncio
    async def test_cross_harness_writes_keep_source_and_session_provenance(
        self,
        test_project: Project,
        test_agent: Agent,
        db_session,
        monkeypatch,
    ) -> None:
        import httpx

        from loom.mcp.server import write_context

        monkeypatch.setenv("LOOM_API_KEY", str(test_agent.id))
        monkeypatch.setenv("LOOM_PROJECT_ID", str(test_project.id))
        monkeypatch.setenv("LOOM_API_URL", "http://test")

        class MockAsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                from loom.api.main import app

                super().__init__(transport=ASGITransport(app=app), base_url="http://test")

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        content = f"Cross-harness result {test_project.id}"

        for source, session in (
            ("claude_code", "claude-session"),
            ("opencode", "opencode-session"),
        ):
            monkeypatch.setenv("LOOM_SOURCE_TYPE", source)
            monkeypatch.setenv("LOOM_SESSION_ID", session)
            result = await write_context(
                content=content,
                type="task_result",
                task_name=f"{source} handoff",
                tests=[{"command": "pytest -q", "status": "passed"}],
            )
            assert "created" in result
            assert f"source={source}" in result
            assert f"session={session}" in result

        units = (
            await db_session.execute(
                select(ContextUnit)
                .where(ContextUnit.content == content)
                .order_by(ContextUnit.source_type)
            )
        ).scalars().all()
        assert [(unit.source_type, unit.source_session_id) for unit in units] == [
            ("claude_code", "claude-session"),
            ("opencode", "opencode-session"),
        ]
        assert [unit.context_metadata["task_name"] for unit in units] == [
            "claude_code handoff",
            "opencode handoff",
        ]

    @pytest.mark.asyncio
    async def test_missing_config_raises_error(self, monkeypatch, tmp_path) -> None:
        """MCP server raises helpful error when config is missing."""
        from loom.mcp.server import _check_config

        # Temporarily clear env vars
        old_key = os.environ.pop("LOOM_API_KEY", None)
        old_pid = os.environ.pop("LOOM_PROJECT_ID", None)
        monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path))

        try:
            with pytest.raises(ValueError, match="Missing Loom project configuration"):
                _check_config()
        finally:
            if old_key:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid:
                os.environ["LOOM_PROJECT_ID"] = old_pid
