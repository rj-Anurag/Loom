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
    *,
    source_url: str = "https://claude.ai/chat/history-test",
    source_session_id: str | None = None,
    type_: str = "message",
    parent_ids: list[str] | None = None,
) -> dict:
    body = {
        "client_uuid": str(uuid.uuid4()),
        "type": type_,
        "content": content,
        "source_url": source_url,
        "source_session_id": source_session_id,
    }
    if parent_ids is None:
        body["version"] = 1
    else:
        body["parent_ids"] = parent_ids
    response = await client.post(
        f"/v1/projects/{project.id}/context",
        headers=headers,
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


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


async def test_history_filters_before_pagination_and_returns_parent_ids(
    client: AsyncClient,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    parent = await _write_message(
        client,
        history_project,
        history_headers,
        "User: filtered parent",
        source_session_id="session-a",
    )
    child = await _write_message(
        client,
        history_project,
        history_headers,
        "AI: filtered child",
        source_session_id="session-a",
        parent_ids=[parent["id"]],
    )
    await _write_message(
        client,
        history_project,
        history_headers,
        "Other session decision",
        source_session_id="session-b",
        type_="decision",
    )

    response = await client.get(
        f"/v1/projects/{history_project.id}/context/history",
        headers=history_headers,
        params={
            "limit": 1,
            "source_type": "browser_chat",
            "source_session_id": "session-a",
            "type": "message",
        },
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert [unit["id"] for unit in page["units"]] == [child["id"]]
    assert page["units"][0]["parent_ids"] == [parent["id"]]
    assert page["has_more"] is True

    next_page = await client.get(
        f"/v1/projects/{history_project.id}/context/history",
        headers=history_headers,
        params={
            "limit": 1,
            "cursor": page["next_cursor"],
            "source_type": "browser_chat",
            "source_session_id": "session-a",
            "type": "message",
        },
    )
    assert [unit["id"] for unit in next_page.json()["units"]] == [parent["id"]]


async def test_sources_group_browser_urls_and_harness_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
    history_project: Project,
    history_agent: Agent,
    history_headers: dict[str, str],
) -> None:
    await _write_message(
        client,
        history_project,
        history_headers,
        "Browser one",
        source_url="https://Claude.AI/chat/source/#first",
    )
    await _write_message(
        client,
        history_project,
        history_headers,
        "Browser two",
        source_url="https://claude.ai/chat/source",
    )

    local_agent = Agent(project_id=history_project.id, kind="local", name="OpenCode")
    db_session.add(local_agent)
    await db_session.commit()
    for session_id in ("open-one", "open-two", None):
        response = await client.post(
            f"/v1/projects/{history_project.id}/context",
            headers={"Authorization": f"Bearer {local_agent.id}"},
            json={
                "client_uuid": str(uuid.uuid4()),
                "type": "decision",
                "content": f"Harness {session_id}",
                "source_type": "opencode" if session_id else "mcp_agent",
                "source_session_id": session_id,
            },
        )
        assert response.status_code == 201, response.text

    response = await client.get(
        f"/v1/projects/{history_project.id}/context/sources",
        headers=history_headers,
    )
    assert response.status_code == 200, response.text
    sources = response.json()["sources"]
    browser = [source for source in sources if source["source_type"] == "browser_chat"]
    assert len(browser) == 1
    assert browser[0]["source_url"] == "https://claude.ai/chat/source"
    assert browser[0]["unit_count"] == 2
    assert browser[0]["agent_id"] == str(history_agent.id)
    assert {source["source_session_id"] for source in sources} == {
        None,
        "open-one",
        "open-two",
    }


async def test_sources_reject_cross_project_credentials(
    client: AsyncClient,
    db_session: AsyncSession,
    history_headers: dict[str, str],
) -> None:
    other_project = Project(name="Private Sources")
    db_session.add(other_project)
    await db_session.commit()
    response = await client.get(
        f"/v1/projects/{other_project.id}/context/sources",
        headers=history_headers,
    )
    assert response.status_code == 403


async def test_sources_returns_empty_list_for_empty_project(
    client: AsyncClient,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    response = await client.get(
        f"/v1/projects/{history_project.id}/context/sources",
        headers=history_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"sources": []}
