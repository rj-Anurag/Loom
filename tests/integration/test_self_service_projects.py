"""RED contract tests for project visibility under public user sessions."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project
from loom.security import generate_api_key, hash_api_key

PASSWORD = "Correct-Horse-Battery-Staple-42!"


async def _signup(client: AsyncClient, label: str) -> dict[str, Any]:
    email_label = label.lower().replace(" ", "-")
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"{email_label}-{uuid.uuid4()}@example.com",
            "password": PASSWORD,
            "display_name": label,
            "client_kind": "cli",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_session_authenticated_project_list_contains_only_memberships(
    client: AsyncClient,
) -> None:
    first_user = await _signup(client, "First User")
    second_user = await _signup(client, "Second User")

    response = await client.get(
        "/v1/projects",
        headers={"Authorization": f"Bearer {first_user['session_token']}"},
    )

    assert response.status_code == 200, response.text
    project_ids = {item["id"] for item in response.json()}
    assert project_ids == {first_user["project_id"]}
    assert second_user["project_id"] not in project_ids


async def test_signup_project_api_key_stays_scoped_to_its_project(
    client: AsyncClient,
) -> None:
    first_user = await _signup(client, "Scoped Agent")
    second_user = await _signup(client, "Other Project")
    headers = {"Authorization": f"Bearer {first_user['project_api_key']}"}

    list_response = await client.get("/v1/projects", headers=headers)
    cross_project_response = await client.get(
        f"/v1/projects/{second_user['project_id']}",
        headers=headers,
    )

    assert list_response.status_code == 200, list_response.text
    assert [item["id"] for item in list_response.json()] == [first_user["project_id"]]
    assert cross_project_response.status_code == 404, cross_project_response.text


async def test_existing_opaque_agent_keys_remain_project_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Adding user sessions must not widen the legacy agent auth boundary."""
    own_project = Project(name=f"Existing Agent {uuid.uuid4()}")
    other_project = Project(name=f"Private Project {uuid.uuid4()}")
    db_session.add_all([own_project, other_project])
    await db_session.flush()

    api_key = generate_api_key()
    db_session.add(
        Agent(
            project_id=own_project.id,
            kind="local",
            name="Existing CLI agent",
            credentials_ref=hash_api_key(api_key),
        )
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {api_key}"}
    list_response = await client.get("/v1/projects", headers=headers)
    cross_project_response = await client.get(
        f"/v1/projects/{other_project.id}",
        headers=headers,
    )

    assert list_response.status_code == 200, list_response.text
    assert [item["id"] for item in list_response.json()] == [str(own_project.id)]
    assert cross_project_response.status_code == 404, cross_project_response.text


async def test_account_session_provisions_and_revokes_a_client_key(
    client: AsyncClient,
) -> None:
    signup = await _signup(client, "Credential Owner")
    project_id = signup["project_id"]
    user_headers = {"Authorization": f"Bearer {signup['session_token']}"}

    provisioned = await client.post(
        f"/v1/projects/{project_id}/agents",
        headers=user_headers,
        json={"kind": "browser", "name": "Loom Extension"},
    )
    assert provisioned.status_code == 201, provisioned.text
    credential = provisioned.json()
    assert credential["api_key"].startswith("loom_")

    listed = await client.get(f"/v1/projects/{project_id}/agents", headers=user_headers)
    assert listed.status_code == 200, listed.text
    assert credential["agent_id"] in {agent["id"] for agent in listed.json()}
    assert all("api_key" not in agent for agent in listed.json())

    revoked = await client.delete(
        f"/v1/projects/{project_id}/agents/{credential['agent_id']}",
        headers=user_headers,
    )
    assert revoked.status_code == 204, revoked.text
    rejected = await client.get(
        "/v1/projects",
        headers={"Authorization": f"Bearer {credential['api_key']}"},
    )
    assert rejected.status_code == 401


async def test_account_can_create_an_additional_owned_project(client: AsyncClient) -> None:
    signup = await _signup(client, "Multi Project")
    headers = {"Authorization": f"Bearer {signup['session_token']}"}

    created = await client.post(
        "/v1/projects",
        headers=headers,
        json={
            "name": "Second Workspace",
            "client_kind": "cli",
            "client_name": "Second CLI",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["api_key"].startswith("loom_")

    listed = await client.get("/v1/projects", headers=headers)
    assert listed.status_code == 200, listed.text
    assert {project["id"] for project in listed.json()} == {
        signup["project_id"],
        created.json()["id"],
    }


async def test_account_reads_project_history_without_minting_dashboard_key(
    client: AsyncClient,
) -> None:
    signup = await _signup(client, "History Owner")
    project_id = signup["project_id"]
    written = await client.post(
        f"/v1/projects/{project_id}/context",
        headers={"Authorization": f"Bearer {signup['project_api_key']}"},
        json={
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "Account history works without another agent key.",
            "version": 1,
        },
    )
    assert written.status_code == 201, written.text

    history = await client.get(
        f"/v1/projects/{project_id}/history",
        headers={"Authorization": f"Bearer {signup['session_token']}"},
    )
    assert history.status_code == 200, history.text
    assert history.json()["units"][0]["content"].startswith("Account history works")
