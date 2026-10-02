"""Terminal conversation API contract and trust boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project
from loom.services.context.service import rebuild_projections


@pytest_asyncio.fixture
async def conversation_project(db_session: AsyncSession) -> Project:
    project = Project(name="Conversation Capture")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def conversation_agent(db_session: AsyncSession, conversation_project: Project) -> Agent:
    agent = Agent(project_id=conversation_project.id, kind="local")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def test_conversation_batch_roles_parents_and_idempotency(
    client: AsyncClient,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    user_id, assistant_id = uuid.uuid4(), uuid.uuid4()
    native_session = str(uuid.uuid4())
    body = {
        "source_type": "codex_cli",
        "source_session_id": native_session,
        "messages": [
            {
                "client_uuid": str(user_id),
                "role": "user",
                "content": "Use the amber token",
                "occurred_at": datetime.now(UTC).isoformat(),
                "turn_id": "turn-1",
                "sequence": 0,
            },
            {
                "client_uuid": str(assistant_id),
                "role": "assistant",
                "content": "Understood",
                "occurred_at": datetime.now(UTC).isoformat(),
                "turn_id": "turn-1",
                "sequence": 1,
                "parent_client_uuid": str(user_id),
            },
        ],
    }
    url = f"/v1/projects/{conversation_project.id}/conversations/messages"
    headers = {"Authorization": f"Bearer {conversation_agent.id}"}
    first = await client.post(url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert [item["created"] for item in first.json()["messages"]] == [True, True]
    replay = await client.post(url, headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert [item["created"] for item in replay.json()["messages"]] == [False, False]

    history = await client.get(
        f"/v1/projects/{conversation_project.id}/context/history",
        headers=headers,
        params={"source_session_id": native_session},
    )
    units = history.json()["units"]
    assert len(units) == 2
    by_role = {unit["metadata"]["conversation_role"]: unit for unit in units}
    assert by_role["user"]["trust_tier"] == "user"
    assert by_role["assistant"]["trust_tier"] == "agent"
    assert by_role["assistant"]["parent_ids"] == [by_role["user"]["id"]]
    assert by_role["user"]["occurred_at"]
    sources = await client.get(
        f"/v1/projects/{conversation_project.id}/context/sources",
        headers=headers,
    )
    source = next(
        item for item in sources.json()["sources"] if item["source_session_id"] == native_session
    )
    assert source["first_occurred_at"]
    assert source["last_occurred_at"]
    retrieved = await client.get(
        f"/v1/projects/{conversation_project.id}/context",
        headers=headers,
        params={"query": "amber token"},
    )
    assert retrieved.status_code == 200, retrieved.text
    assert any(unit["content"] == "Use the amber token" for unit in retrieved.json()["units"])


async def test_conversation_rejects_cross_project_and_bad_role(
    client: AsyncClient,
    db_session: AsyncSession,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    other = Project(name="Other")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    body = {
        "source_type": "codex_cli",
        "source_session_id": "s",
        "messages": [
            {
                "client_uuid": str(uuid.uuid4()),
                "role": "user",
                "content": "output",
                "occurred_at": datetime.now(UTC).isoformat(),
                "sequence": 0,
            }
        ],
    }
    headers = {"Authorization": f"Bearer {conversation_agent.id}"}
    denied = await client.post(
        f"/v1/projects/{other.id}/conversations/messages", headers=headers, json=body
    )
    assert denied.status_code == 403
    body["messages"][0]["role"] = "tool"
    invalid = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers=headers,
        json=body,
    )
    assert invalid.status_code == 422


async def test_conversation_occurrence_survives_event_replay(
    client: AsyncClient,
    db_session: AsyncSession,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    occurred = "2025-03-01T12:30:00+00:00"
    message_id = str(uuid.uuid4())
    native_session = str(uuid.uuid4())
    response = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers={"Authorization": f"Bearer {conversation_agent.id}"},
        json={
            "source_type": "opencode",
            "source_session_id": native_session,
            "messages": [
                {
                    "client_uuid": message_id,
                    "role": "user",
                    "content": "Remember the copper gate",
                    "occurred_at": occurred,
                    "sequence": 0,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    unit_id = uuid.UUID(response.json()["messages"][0]["id"])
    await db_session.execute(text("DELETE FROM context_units WHERE id = :id"), {"id": unit_id})
    await db_session.commit()
    await rebuild_projections(db_session, conversation_project.id)
    await db_session.commit()
    rebuilt = await db_session.execute(
        text("SELECT occurred_at, metadata FROM context_units WHERE id = :id"),
        {"id": unit_id},
    )
    row = rebuilt.one()
    assert row.occurred_at.isoformat() == occurred
    assert row.metadata["conversation_role"] == "user"


async def test_invalid_batch_does_not_store_earlier_messages(
    client: AsyncClient,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    first_id = uuid.uuid4()
    native_session = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {conversation_agent.id}"}
    response = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers=headers,
        json={
            "source_type": "codex_cli",
            "source_session_id": native_session,
            "messages": [
                {
                    "client_uuid": str(first_id),
                    "role": "user",
                    "content": "Should roll back",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                },
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "bad",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 1,
                    "parent_client_uuid": str(uuid.uuid4()),
                },
            ],
        },
    )
    assert response.status_code == 400
    history = await client.get(
        f"/v1/projects/{conversation_project.id}/context/history",
        headers=headers,
        params={"source_session_id": native_session},
    )
    assert history.json()["units"] == []


async def test_conversation_rejects_reused_session_in_another_project(
    client: AsyncClient,
    db_session: AsyncSession,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    session_id = str(uuid.uuid4())
    first = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers={"Authorization": f"Bearer {conversation_agent.id}"},
        json={
            "source_type": "codex_cli",
            "source_session_id": session_id,
            "messages": [
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "user",
                    "content": "First project",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                }
            ],
        },
    )
    assert first.status_code == 200
    other = Project(name="Second project")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_agent = Agent(project_id=other.id, kind="local")
    db_session.add(other_agent)
    await db_session.commit()
    await db_session.refresh(other_agent)
    denied = await client.post(
        f"/v1/projects/{other.id}/conversations/messages",
        headers={"Authorization": f"Bearer {other_agent.id}"},
        json={
            "source_type": "codex_cli",
            "source_session_id": session_id,
            "messages": [
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "user",
                    "content": "Second project",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                }
            ],
        },
    )
    assert denied.status_code == 403


async def test_conversation_limits_batch_count(
    client: AsyncClient,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    response = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers={"Authorization": f"Bearer {conversation_agent.id}"},
        json={
            "source_type": "codex_cli",
            "source_session_id": str(uuid.uuid4()),
            "messages": [
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "user",
                    "content": "bulk",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": i,
                }
                for i in range(101)
            ],
        },
    )
    assert response.status_code == 422
    invalid_source = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers={"Authorization": f"Bearer {conversation_agent.id}"},
        json={
            "source_type": "browser_chat",
            "source_session_id": str(uuid.uuid4()),
            "messages": [
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "user",
                    "content": "bad source",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                }
            ],
        },
    )
    assert invalid_source.status_code == 422


async def test_conversation_limits_total_payload(
    client: AsyncClient,
    conversation_project: Project,
    conversation_agent: Agent,
) -> None:
    response = await client.post(
        f"/v1/projects/{conversation_project.id}/conversations/messages",
        headers={"Authorization": f"Bearer {conversation_agent.id}"},
        json={
            "source_type": "codex_cli",
            "source_session_id": str(uuid.uuid4()),
            "messages": [
                {
                    "client_uuid": str(uuid.uuid4()),
                    "role": "user",
                    "content": "x" * 90000,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": i,
                }
                for i in range(12)
            ],
        },
    )
    assert response.status_code == 413
