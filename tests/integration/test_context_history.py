"""Chronological context-history API tests for the dashboard."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.models import Agent, Project, ProjectMembership, User
from loom.services.accounts.service import issue_user_session
from loom.services.context.service import list_context_history, write_context
from loom.services.context.sources import remove_source


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


async def test_removed_browser_source_stays_out_of_history_bundle_and_summary(
    client: AsyncClient,
    db_session: AsyncSession,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    removed_url = "https://claude.ai/chat/remove-me"
    await _write_message(
        client,
        history_project,
        history_headers,
        "User: cobalt falcon secret",
        source_url=removed_url,
    )
    await _write_message(
        client,
        history_project,
        history_headers,
        "User: amber otter remains",
        source_url="https://claude.ai/chat/keep-me",
    )

    count = await remove_source(
        db_session,
        history_project.id,
        source_type="browser_chat",
        source_url=removed_url,
    )
    assert count == 1

    history = await client.get(
        f"/v1/projects/{history_project.id}/context/history", headers=history_headers
    )
    assert history.status_code == 200
    assert [unit["content"] for unit in history.json()["units"]] == ["User: amber otter remains"]

    bundle = await client.post(
        f"/v1/projects/{history_project.id}/context/bundle",
        headers=history_headers,
        json={"prompt": "cobalt falcon secret"},
    )
    assert bundle.status_code == 200
    assert bundle.json()["evidence"] == []

    summary = await client.get(
        f"/v1/projects/{history_project.id}/summary", headers=history_headers
    )
    assert summary.status_code == 200
    assert "cobalt falcon" not in summary.json()["summary"]
    assert "amber otter" in summary.json()["summary"]

    replay = await client.post(
        f"/v1/projects/{history_project.id}/context",
        headers=history_headers,
        json={
            "client_uuid": str(uuid.uuid4()),
            "type": "message",
            "content": "User: cobalt falcon secret returns",
            "source_url": removed_url,
            "version": 1,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "SOURCE_REMOVED"


async def test_project_summary_caches_updates_and_rebuilds_after_removal(
    client: AsyncClient,
    db_session: AsyncSession,
    history_project: Project,
    history_headers: dict[str, str],
    monkeypatch,
) -> None:
    from loom.services.context import project_summary

    calls = []

    class Provider:
        async def summarize(self, inputs):
            calls.append(inputs)
            if len(calls) == 1:
                return "## Overview\n- Aurora is teal [1]."
            if len(calls) == 2:
                return "## Overview\n- Aurora is teal [1].\n- Retry is seven [2]."
            return "## Overview\n- Retry is seven [1]."

    monkeypatch.setattr(settings, "summarization_provider", "groq")
    monkeypatch.setattr(project_summary, "from_llm_config", Provider)
    url = "https://claude.ai/chat/aurora"
    await _write_message(
        client,
        history_project,
        history_headers,
        "Aurora is teal",
        source_url=url,
    )
    endpoint = f"/v1/projects/{history_project.id}/summary"
    first = await client.get(endpoint, headers=history_headers)
    assert first.status_code == 200
    assert first.json()["mode"] == "ai"
    cached = await client.get(endpoint, headers=history_headers)
    assert cached.json() == first.json()
    assert len(calls) == 1

    await _write_message(client, history_project, history_headers, "Retry is seven")
    updated = await client.get(endpoint, headers=history_headers)
    assert updated.json()["context_count"] == 2
    assert len(calls) == 2
    assert calls[1][0]["type"] == "summary"
    assert "Aurora is teal" in calls[1][0]["content"]
    assert "Retry is seven" in calls[1][1]["content"]
    assert len(calls[1]) == 2

    await remove_source(db_session, history_project.id, source_type="browser_chat", source_url=url)
    rebuilt = await client.get(endpoint, headers=history_headers)
    assert rebuilt.json()["context_count"] == 1
    assert "Aurora" not in rebuilt.json()["summary"]
    assert all(item["type"] != "summary" for item in calls[2])
    assert rebuilt.json()["citations"][0]["excerpt"] == "Retry is seven"


async def test_project_summary_provider_failure_returns_cited_highlights(
    client: AsyncClient,
    history_project: Project,
    history_headers: dict[str, str],
    monkeypatch,
) -> None:
    from loom.services.context import project_summary

    class Provider:
        async def summarize(self, inputs):
            raise RuntimeError("Unavailable")

    monkeypatch.setattr(settings, "summarization_provider", "groq")
    monkeypatch.setattr(project_summary, "from_llm_config", Provider)
    await _write_message(client, history_project, history_headers, "Aurora is teal")
    response = await client.get(
        f"/v1/projects/{history_project.id}/summary",
        headers=history_headers,
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "fallback"
    assert "[1]" in response.json()["summary"]
    assert response.json()["citations"][0]["excerpt"] == "Aurora is teal"
    assert "source_session_id" not in response.json()["citations"][0]


async def test_removed_cli_session_does_not_hide_other_sessions(
    db_session: AsyncSession,
    history_project: Project,
) -> None:
    agent = Agent(project_id=history_project.id, kind="local")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    for session_id in ("removed-session", "kept-session"):
        await write_context(
            db_session,
            history_project.id,
            agent.id,
            client_uuid=uuid.uuid4(),
            type_="message",
            content=f"User: {session_id}",
            version=1,
            source_type="codex_cli",
            source_session_id=session_id,
        )
    count = await remove_source(
        db_session,
        history_project.id,
        source_type="codex_cli",
        source_session_id="removed-session",
        agent_id=agent.id,
    )
    assert count == 1
    history = await list_context_history(db_session, history_project.id, agent.id)
    assert [unit["content"] for unit in history["units"]] == ["User: kept-session"]
    with pytest.raises(ValueError, match="SOURCE_REMOVED"):
        await write_context(
            db_session,
            history_project.id,
            agent.id,
            client_uuid=uuid.uuid4(),
            type_="message",
            content="User: removed-session returns",
            version=1,
            source_type="codex_cli",
            source_session_id="removed-session",
        )


async def test_member_can_remove_linked_chat_without_cross_project_access(
    client: AsyncClient,
    db_session: AsyncSession,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    user = User(email=f"source-delete-{uuid.uuid4()}@example.test", display_name="Owner")
    other = Project(name="Other owner's project")
    db_session.add_all([user, other])
    await db_session.flush()
    db_session.add(
        ProjectMembership(
            project_id=history_project.id,
            user_id=user.id,
            role="owner",
        )
    )
    await db_session.commit()
    _, token = await issue_user_session(db_session, user_id=user.id, client_kind="web")
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://claude.ai/chat/link-only"
    linked = await client.post(
        f"/v1/projects/{history_project.id}/link/chat",
        headers=history_headers,
        json={"chat_url": url, "title": "Link only", "platform": "claude.ai"},
    )
    assert linked.status_code == 200
    summary = await client.get(
        f"/v1/projects/{history_project.id}/summary",
        headers=history_headers,
    )
    assert summary.status_code == 200
    assert "Link only" in summary.json()["summary"]
    assert summary.json()["citations"][0]["source_url"] == url

    foreign = await client.post(
        f"/v1/projects/{other.id}/sources/remove",
        headers=headers,
        json={"source_type": "browser_chat", "source_url": url},
    )
    assert foreign.status_code == 404
    removed = await client.post(
        f"/v1/projects/{history_project.id}/sources/remove",
        headers=headers,
        json={"source_type": "browser_chat", "source_url": url},
    )
    assert removed.status_code == 200
    assert removed.json()["removed_units"] == 0
    chats = await client.get(f"/v1/projects/{history_project.id}/chats", headers=headers)
    assert chats.json() == []
    after_removal = await client.get(
        f"/v1/projects/{history_project.id}/summary",
        headers=history_headers,
    )
    assert after_removal.json()["mode"] == "empty"
    assert after_removal.json()["citations"] == []
    relinked = await client.post(
        f"/v1/projects/{history_project.id}/link/chat",
        headers=history_headers,
        json={"chat_url": url, "title": "Link only"},
    )
    assert relinked.status_code == 409
    assert relinked.json()["detail"] == "SOURCE_REMOVED"


async def test_removal_invalidates_only_summaries_derived_from_that_source(
    client: AsyncClient,
    db_session: AsyncSession,
    history_project: Project,
    history_headers: dict[str, str],
) -> None:
    removed_url = "https://claude.ai/chat/derived-removed"
    kept_url = "https://claude.ai/chat/derived-kept"
    removed = await _write_message(
        client,
        history_project,
        history_headers,
        "Aurora is teal",
        source_url=removed_url,
    )
    kept = await _write_message(
        client,
        history_project,
        history_headers,
        "Retry is seven",
        source_url=kept_url,
    )
    await _write_message(
        client,
        history_project,
        history_headers,
        "Summary: Aurora is teal",
        source_url=removed_url,
        type_="summary",
        parent_ids=[removed["id"]],
    )
    await _write_message(
        client,
        history_project,
        history_headers,
        "Summary: Retry is seven",
        source_url=kept_url,
        type_="summary",
        parent_ids=[kept["id"]],
    )
    await remove_source(
        db_session,
        history_project.id,
        source_type="browser_chat",
        source_url=removed_url,
    )
    history = await client.get(
        f"/v1/projects/{history_project.id}/context/history",
        headers=history_headers,
    )
    assert [unit["content"] for unit in history.json()["units"]] == [
        "Summary: Retry is seven",
        "Retry is seven",
    ]


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
