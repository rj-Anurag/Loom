"""Integration tests for MCP tool definitions.

Tests cover:
- read_context tool: returns ranked units, respects budget, handles min_trust_tier
- write_context tool: creates units, idempotent via content-based client_uuid
- write_context tool: supports parent_ids / parent_relations
- get_project_summary tool: returns summary-type units only
- ToolRegistry: lists 3 tools with valid MCP schemas
- Error handling: missing required fields, unknown tool names
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _clean_context_tables(db_session: AsyncSession) -> None:
    """Truncate context_units, context_edges, and event_log between tests.

    This avoids collisions from deterministic ``client_uuid`` values (UUID v5
    based on content+type) that persist across test runs.
    """
    from sqlalchemy import text

    for table in ("context_edges", "context_units", "event_log"):
        await db_session.execute(text(f"TRUNCATE {table} CASCADE"))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="MCP Tools Project")
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
async def tool_registry(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> Any:
    """Create a ToolRegistry bound to the test session / project / agent."""
    from loom.services.context.mcp_tools import ToolRegistry

    return ToolRegistry(
        session=db_session,
        project_id=test_project.id,
        agent_id=test_agent.id,
    )


# ── ToolRegistry ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_lists_three_tools(
    tool_registry: Any,
) -> None:
    """ToolRegistry.list_tools() returns definitions for all 3 tools."""
    tools = tool_registry.list_tools()
    assert len(tools) == 3

    names = {t["name"] for t in tools}
    assert names == {"read_context", "write_context", "get_project_summary"}

    # Each tool must have a name, description, and inputSchema
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        assert "properties" in t["inputSchema"]
        assert "required" in t["inputSchema"]


@pytest.mark.asyncio
async def test_registry_unknown_tool(tool_registry: Any) -> None:
    """Calling an unknown tool name returns a structured error."""
    result = await tool_registry.call("nonexistent_tool", {})
    assert "error" in result
    assert "unknown" in result["error"].lower()


# ── read_context tool ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_context_tool_returns_units(
    client: Any,  # noqa: ARG001 — used to ensure app is importable
    tool_registry: Any,
    test_project: Project,
    test_agent: Agent,
) -> None:
    """read_context tool returns ranked context units."""
    # First write some data via the tool
    await tool_registry.call("write_context", {
        "content": "Decision: use FastAPI for the API layer",
        "type": "decision",
    })
    await tool_registry.call("write_context", {
        "content": "Message: I think we should use FastAPI",
        "type": "message",
    })
    await tool_registry.call("write_context", {
        "content": "Summary: Tech stack overview",
        "type": "summary",
    })

    # Now read with a query
    result = await tool_registry.call("read_context", {
        "task_description": "FastAPI decision",
        "token_budget": 5000,
    })
    assert "units" in result
    assert len(result["units"]) > 0
    assert result["total_tokens"] <= 5000

    # At least one unit should mention FastAPI
    contents = [u["content"].lower() for u in result["units"]]
    assert any("fastapi" in c for c in contents)


@pytest.mark.asyncio
async def test_read_context_tool_respects_budget(
    tool_registry: Any,
) -> None:
    """read_context respects a tight token budget."""
    budget = 100
    result = await tool_registry.call("read_context", {
        "task_description": "test",
        "token_budget": budget,
    })
    assert "units" in result
    assert result["total_tokens"] <= budget
    assert result["budget_used"] <= budget


@pytest.mark.asyncio
async def test_read_context_tool_min_trust_tier(
    tool_registry: Any,
    test_project: Project,
    test_agent: Agent,
    db_session: AsyncSession,
) -> None:
    """read_context with min_trust_tier filters lower-tier results.

    We write an agent-tier and an external_tool-tier unit,
    then query with min_trust_tier='agent' and expect only agent-tier back.
    """
    from loom.services.context.service import write_context

    # Write a unit with trust_tier='agent'
    unit_agent, _ = await write_context(
        db_session, test_project.id, test_agent.id,
        client_uuid=uuid.uuid4(),
        type_="message",
        content="Agent analysis of architecture decision",
        version=1,
        trust_tier="agent",
    )

    # Write a unit with trust_tier='external_tool'
    unit_ext, _ = await write_context(
        db_session, test_project.id, test_agent.id,
        client_uuid=uuid.uuid4(),
        type_="message",
        content="External linter report on code quality",
        version=1,
        trust_tier="external_tool",
    )

    # Query with min_trust_tier='agent' — should filter out external_tool
    result = await tool_registry.call("read_context", {
        "task_description": "architecture",
        "token_budget": 5000,
        "min_trust_tier": "agent",
    })
    assert len(result["units"]) > 0
    for unit in result["units"]:
        assert unit["trust_tier"] == "agent", (
            f"Expected agent tier, got {unit['trust_tier']}"
        )


# ── write_context tool ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_context_tool_creates_unit(
    tool_registry: Any,
) -> None:
    """write_context creates a unit and returns its ID."""
    result = await tool_registry.call("write_context", {
        "content": "Decision: use asyncpg for PostgreSQL access",
        "type": "decision",
    })
    assert "id" in result
    assert "client_uuid" in result
    assert "created_at" in result
    # Verify it's a valid UUID
    uuid.UUID(result["id"])


@pytest.mark.asyncio
async def test_write_context_tool_idempotent(
    tool_registry: Any,
) -> None:
    """Same content + type produces the same ID (idempotent)."""
    result1 = await tool_registry.call("write_context", {
        "content": "Identical content for idempotency test",
        "type": "message",
    })
    result2 = await tool_registry.call("write_context", {
        "content": "Identical content for idempotency test",
        "type": "message",
    })
    assert result1["id"] == result2["id"]
    assert result1["client_uuid"] == result2["client_uuid"]


@pytest.mark.asyncio
async def test_write_context_tool_with_parents(
    tool_registry: Any,
) -> None:
    """write_context accepts parent_ids and parent_relations."""
    # Write a parent
    parent = await tool_registry.call("write_context", {
        "content": "Parent: use Redis caching",
        "type": "decision",
    })
    # Write a child referencing it
    child = await tool_registry.call("write_context", {
        "content": "Implemented Redis caching layer",
        "type": "task_result",
        "parent_ids": [parent["id"]],
        "parent_relations": ["derived_from"],
    })
    assert child["id"] != parent["id"]


@pytest.mark.asyncio
async def test_write_context_tool_missing_required_field(
    tool_registry: Any,
) -> None:
    """write_context returns structured error for missing required field."""
    result = await tool_registry.call("write_context", {
        "type": "message",
        # missing "content"
    })
    assert "error" in result


# ── get_project_summary tool ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_project_summary_tool(
    tool_registry: Any,
    test_project: Project,
    test_agent: Agent,
) -> None:
    """get_project_summary returns summary-type units."""
    # Write some units via the tool, including a summary
    await tool_registry.call("write_context", {
        "content": "Project overview: building an AI context server",
        "type": "summary",
    })
    await tool_registry.call("write_context", {
        "content": "Technical stack: Python, FastAPI, PostgreSQL",
        "type": "summary",
    })
    await tool_registry.call("write_context", {
        "content": "A random message for testing",
        "type": "message",
    })

    result = await tool_registry.call("get_project_summary", {})
    assert "units" in result
    assert len(result["units"]) > 0
    for unit in result["units"]:
        assert unit["type"] == "summary", (
            f"Expected summary type, got {unit['type']}"
        )
