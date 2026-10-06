"""Prompt-specific bundle retrieval and project boundaries."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, ContextEdge, ContextUnit, Project
from loom.models.context_edges import EdgeRelation


@pytest.mark.asyncio
async def test_bundle_returns_cited_conversation_and_linked_result(
    client,
    db_session: AsyncSession,
) -> None:
    project = Project(name="Bundle project")
    other = Project(name="Other project")
    db_session.add_all([project, other])
    await db_session.flush()
    agent = Agent(project_id=project.id, kind="local")
    other_agent = Agent(project_id=other.id, kind="local")
    db_session.add_all([agent, other_agent])
    await db_session.flush()

    def unit(
        content: str,
        *,
        project_id=None,
        agent_id=None,
        source="session-one",
        type_="message",
        source_type="codex_cli",
        source_url=None,
    ):
        return ContextUnit(
            project_id=project_id or project.id,
            agent_id=agent_id or agent.id,
            client_uuid=uuid.uuid4(),
            type=type_,
            trust_tier="agent",
            content=content,
            source_type=source_type,
            source_session_id=source,
            source_url=source_url,
            context_metadata={},
            version=1,
        )

    first = unit("User: How should login tokens expire?")
    match = unit("Assistant: Login tokens expire after one hour")
    decision = unit("Decision: login expiry is one hour", source="decision", type_="decision")
    noise = unit("Weather forecast is sunny", source="other")
    browser = unit(
        "User: Login expiry should be one hour",
        source="browser-one",
        source_type="browser_chat",
        source_url="https://example.test/chat/one",
    )
    foreign = unit(
        "Login tokens expire after ten years", project_id=other.id, agent_id=other_agent.id
    )
    db_session.add_all([first, match, decision, noise, browser, foreign])
    await db_session.flush()
    db_session.add(
        ContextEdge(parent_id=match.id, child_id=decision.id, relation=EdgeRelation.derived_from)
    )
    await db_session.commit()

    response = await client.post(
        f"/v1/projects/{project.id}/context/bundle",
        json={"prompt": "login tokens expiry", "budget": 1000},
        headers={"Authorization": f"Bearer {agent.id}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    ids = {item["id"] for item in data["evidence"]}
    assert str(first.id) in ids
    assert str(match.id) in ids
    assert str(decision.id) in ids
    assert str(browser.id) in ids
    assert str(noise.id) not in ids
    assert str(foreign.id) not in ids
    by_id = {item["id"]: item for item in data["evidence"]}
    assert "source_url" not in by_id[str(match.id)]
    assert "source_session_id" not in by_id[str(browser.id)]
    assert "[1]" in data["brief"]
    assert data["total_tokens"] <= 1000

    miss = await client.post(
        f"/v1/projects/{project.id}/context/bundle",
        json={"prompt": "unicorn spacecraft", "budget": 500},
        headers={"Authorization": f"Bearer {agent.id}"},
    )
    assert miss.status_code == 200
    assert miss.json()["evidence"] == []

    forbidden = await client.post(
        f"/v1/projects/{other.id}/context/bundle",
        json={"prompt": "login tokens"},
        headers={"Authorization": f"Bearer {agent.id}"},
    )
    assert forbidden.status_code == 403
