"""Chronological context-history API tests for the dashboard."""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


@pytest_asyncio.fixture
async def history_project(db_session: AsyncSession) -> Project:
    project = Project(name="History Test Project")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def history_agent(db_session: AsyncSession, history_project: Project) -> Agent:
    agent = Agent(project_id=history_project.id, kind="browser")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest_asyncio.fixture
async def history_headers(history_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {history_agent.id}"}


async def _write_message(
    client: AsyncClient,
    project: Project,
    headers: dict[str, str],
    content: str,
) -> None:
    response = await client.post(
        f"/v1/projects/{project.id}/context",
        headers=headers,
        json={
            "client_uuid": str(uuid.uuid4()),
            "type": "message",
            "content": content,
            "version": 1,
            "source_url": "https://claude.ai/chat/history-test",
        },
    )
    assert response.status_code == 201, response.text


async def test_history_cursor_paginates_without_losing_messages(
    client: AsyncClient,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    for content in ("User: first", "AI: second", "User: third"):
        await _write_message(client, history_project, history_headers, content)

    first_page = await client.get(
        f"/v1/projects/{history_project.id}/context/history?limit=2",
        headers=history_headers,
    )
    assert first_page.status_code == 200, first_page.text
    first_data = first_page.json()
    assert [unit["content"] for unit in first_data["units"]] == [
        "User: third",
        "AI: second",
    ]
    assert first_data["has_more"] is True
    assert first_data["next_cursor"]

    second_page = await client.get(
        f"/v1/projects/{history_project.id}/context/history",
        headers=history_headers,
        params={"limit": 2, "cursor": first_data["next_cursor"]},
    )
    assert second_page.status_code == 200, second_page.text
    second_data = second_page.json()
    assert [unit["content"] for unit in second_data["units"]] == ["User: first"]
    assert second_data["has_more"] is False
    assert second_data["next_cursor"] is None


async def test_history_rejects_cross_project_credentials(
    client: AsyncClient,
    db_session: AsyncSession,
    history_headers: dict[str, str],
) -> None:
    other_project = Project(name="Private History")
    db_session.add(other_project)
    await db_session.commit()
    await db_session.refresh(other_project)

    response = await client.get(
        f"/v1/projects/{other_project.id}/context/history",
        headers=history_headers,
    )
    assert response.status_code == 403


async def test_history_rejects_malformed_cursor(
    client: AsyncClient,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    response = await client.get(
        f"/v1/projects/{history_project.id}/context/history",
        headers=history_headers,
        params={"cursor": "not-a-valid-cursor"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_CURSOR"
