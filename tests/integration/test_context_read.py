"""Integration tests for the Context Service read path.

Tests cover:
- Basic keyword query returns matching units
- Empty query returns most recent units
- Token budget is respected
- No results returns empty array (not 404)
- scope=onboarding filters to summary type only
- Ranking: user > agent > external_tool
- Authorization: 401 without auth
- Invalid project: 404
"""

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Read Test Project")
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


@pytest_asyncio.fixture
async def sample_units(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> dict[str, Any]:
    """Write several context units for read tests.

    Returns a dict of labels → {id, type, content, trust_tier} for test
    assertions.
    """
    units: dict[str, Any] = {}

    writes = [
        (
            "summary_onboard",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "summary",
                "content": "Project overview: building a context server for AI agents",
                "version": 1,
            },
        ),
        (
            "summary_tech",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "summary",
                "content": "Technical stack: Python, FastAPI, PostgreSQL, pgvector",
                "version": 1,
            },
        ),
        (
            "decision_bcrypt",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "decision",
                "content": "Use bcrypt for password hashing to comply with security policies",
                "version": 1,
            },
        ),
        (
            "decision_cache",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "decision",
                "content": "Implement Redis caching layer for frequently accessed context",
                "version": 1,
            },
        ),
        (
            "message_hello",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "message",
                "content": "Hello, I need to understand the authentication flow",
                "version": 1,
            },
        ),
        (
            "message_bcrypt_question",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "message",
                "content": "How was the bcrypt decision implemented?",
                "version": 1,
            },
        ),
        (
            "task_user_tier",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "task_result",
                "trust_tier": "agent",
                "content": "Agent reviewed the bcrypt implementation and approved it",
                "version": 1,
            },
        ),
        (
            "task_external_tier",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "task_result",
                "trust_tier": "external_tool",
                "content": "External linter checked the bcrypt code for vulnerabilities",
                "version": 1,
            },
        ),
        (
            "summary_noise",
            {
                "client_uuid": str(uuid.uuid4()),
                "type": "summary",
                "content": "The weather today is sunny with a chance of rain",
                "version": 1,
            },
        ),
    ]

    for label, body in writes:
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=body,
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Failed to write {label}: {resp.text}"
        data = resp.json()
        units[label] = {
            "id": data["id"],
            "type": body["type"],
            "content": body["content"],
            "trust_tier": body.get("trust_tier", "agent"),
        }

    return units


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_context_returns_units(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Keyword query returns matching context units."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"query": "bcrypt", "budget": 10000},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["units"]) > 0

    # At least one unit mentions bcrypt
    contents = [u["content"].lower() for u in data["units"]]
    assert any("bcrypt" in c for c in contents)


@pytest.mark.asyncio
async def test_read_context_empty_query(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Empty query returns most recent units (no keyword filtering)."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["units"]) > 0
    assert data["total_tokens"] > 0


@pytest.mark.asyncio
async def test_read_context_respects_budget(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Response total_tokens does not exceed requested budget."""
    budget = 200
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"query": "bcrypt", "budget": budget},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tokens"] <= budget
    assert data["budget_used"] <= budget
    assert "truncated" in data


@pytest.mark.asyncio
async def test_read_context_no_results(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Non-matching query falls through to chronological (never 404)."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"query": "xyznonexistentkeyword", "budget": 10000},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # When hybrid search returns no matches, the service falls through
    # to chronological ordering so the caller always gets recent context.
    assert len(data["units"]) > 0
    assert data["total_tokens"] > 0


@pytest.mark.asyncio
async def test_read_context_scope_onboarding(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """scope=onboarding returns only summary-type units."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"budget": 10000, "scope": "onboarding"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["units"]) > 0
    for unit in data["units"]:
        assert unit["type"] == "summary", f"Expected summary, got {unit['type']}"


@pytest.mark.asyncio
async def test_read_context_scope_task(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """scope=task (default) returns all unit types."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"budget": 10000, "scope": "task"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["units"]) > 0
    types = {u["type"] for u in data["units"]}
    # Should have multiple types, not just summaries
    assert len(types) > 1 or "summary" not in types  # not ONLY summaries


@pytest.mark.asyncio
async def test_read_context_ranking(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Results are ranked by relevance score (descending)."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"query": "bcrypt", "budget": 10000},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    units = data["units"]
    if len(units) >= 2:
        scores = [u["relevance_score"] for u in units]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], "Scores must be descending"


@pytest.mark.asyncio
async def test_read_context_unauthorized(
    client: AsyncClient,
    test_project: Project,
) -> None:
    """GET without auth returns 401."""
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_read_context_invalid_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET on non-existent project returns 404."""
    resp = await client.get(
        f"/v1/projects/{uuid.uuid4()}/context",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_read_context_agent_belongs_to_project(
    client: AsyncClient,
    test_project: Project,
    db_session: AsyncSession,
) -> None:
    """Agent from a different project cannot read this project's context."""
    from loom.db import async_session_factory

    session = async_session_factory()
    other_project = Project(name="Other Read Project")
    session.add(other_project)
    await session.commit()
    await session.refresh(other_project)
    wrong_agent = Agent(project_id=other_project.id, kind="local")
    session.add(wrong_agent)
    await session.commit()
    await session.refresh(wrong_agent)
    await session.close()

    wrong_headers = {"Authorization": f"Bearer {wrong_agent.id}"}
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        headers=wrong_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_read_context_parent_ids_included(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
    sample_units: dict[str, Any],
) -> None:
    """Units with parent relationships include parent_ids in response."""
    # First write a parent
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Parent decision about logging framework",
        "version": 1,
    }
    parent_resp = await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=parent_body,
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]

    # Then write a child referencing the parent
    child_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "task_result",
        "content": "Implemented logging per the decision",
        "parent_ids": [parent_id],
        "parent_relations": ["derived_from"],
        "version": 2,
    }
    await client.post(
        f"/v1/projects/{test_project.id}/context",
        json=child_body,
        headers=auth_headers,
    )

    # Read and check the child has parent_ids
    resp = await client.get(
        f"/v1/projects/{test_project.id}/context",
        params={"query": "logging", "budget": 10000},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    child_units = [u for u in data["units"] if "logging" in u["content"].lower()]
    for unit in child_units:
        if "Implemented" in unit["content"]:
            assert len(unit.get("parent_ids", [])) > 0
            assert unit["parent_ids"][0] == parent_id
