"""RED contract tests for public self-service account authentication.

These tests define the HTTP contract for the first public Loom onboarding
flow: signup provisions a user, a default project, a revocable session, and a
one-time project API key.  They intentionally exercise the API as a client and
do not depend on the future user/session ORM models.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.models import Agent
from loom.security import hash_api_key

PASSWORD = "Correct-Horse-Battery-Staple-42!"


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4()}@example.com"


async def _signup(
    client: AsyncClient,
    *,
    email: str,
    display_name: str = "Ada Lovelace",
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": display_name,
            "client_kind": "cli",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_signup_provisions_user_project_session_and_one_time_api_key(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = _unique_email("signup")

    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Ada Lovelace",
            "client_kind": "cli",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["user"]["email"] == email
    assert data["user"]["display_name"] == "Ada Lovelace"
    assert uuid.UUID(data["user"]["id"])
    project_id = uuid.UUID(data["project_id"])
    assert data["session_token"]
    assert data["project_api_key"].startswith("loom_")
    assert data["session_token"] != data["project_api_key"]

    # The returned project key is immediately usable by CLI/extension clients.
    project_response = await client.get(
        "/v1/projects",
        headers={"Authorization": f"Bearer {data['project_api_key']}"},
    )
    assert project_response.status_code == 200, project_response.text
    assert [item["id"] for item in project_response.json()] == [str(project_id)]

    # "One-time" means the plaintext secret is returned once and only its
    # digest is persisted with the project agent.
    agents = (
        (await db_session.execute(select(Agent).where(Agent.project_id == project_id)))
        .scalars()
        .all()
    )
    matching_agents = [
        agent for agent in agents if agent.credentials_ref == hash_api_key(data["project_api_key"])
    ]
    assert len(matching_agents) == 1
    assert all(agent.credentials_ref != data["project_api_key"] for agent in agents)


async def test_signup_rejects_duplicate_email_with_conflict(
    client: AsyncClient,
) -> None:
    email = _unique_email("duplicate")
    payload = {
        "email": email,
        "password": PASSWORD,
        "display_name": "Grace Hopper",
        "client_kind": "cli",
    }

    first = await client.post("/v1/auth/signup", json=payload)
    second = await client.post("/v1/auth/signup", json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


async def test_signup_requires_email_password_and_display_name(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/v1/auth/signup",
        json={"email": _unique_email("invalid")},
    )

    assert response.status_code == 422, response.text


async def test_email_password_signup_can_be_disabled_for_public_google_deployments(
    client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "email_password_auth_enabled", False)

    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": _unique_email("google-only"),
            "password": PASSWORD,
            "display_name": "Google Only",
            "client_kind": "cli",
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "EMAIL_PASSWORD_AUTH_DISABLED"


async def test_login_returns_session_but_never_reissues_project_api_key(
    client: AsyncClient,
) -> None:
    email = _unique_email("login")
    await _signup(client, email=email, display_name="Margaret Hamilton")

    response = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": PASSWORD, "client_kind": "cli"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["session_token"]
    assert data["user"]["email"] == email
    assert data["user"]["display_name"] == "Margaret Hamilton"
    assert "project_api_key" not in data


async def test_login_rejects_invalid_password(client: AsyncClient) -> None:
    email = _unique_email("wrong-password")
    await _signup(client, email=email)

    response = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": "Definitely-Not-The-Password!",
            "client_kind": "cli",
        },
    )

    assert response.status_code == 401, response.text


async def test_login_rejects_unknown_email_without_account_enumeration(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/v1/auth/login",
        json={
            "email": _unique_email("unknown"),
            "password": PASSWORD,
            "client_kind": "cli",
        },
    )

    assert response.status_code == 401, response.text


async def test_me_returns_the_session_user(client: AsyncClient) -> None:
    email = _unique_email("me")
    signup = await _signup(client, email=email, display_name="Katherine Johnson")

    response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {signup['session_token']}"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == signup["user"]["id"]
    assert data["email"] == email
    assert data["display_name"] == "Katherine Johnson"
    assert "project_api_key" not in data


async def test_me_requires_a_valid_session(client: AsyncClient) -> None:
    response = await client.get("/v1/auth/me")

    assert response.status_code == 401, response.text


async def test_logout_revokes_the_current_session(client: AsyncClient) -> None:
    signup = await _signup(client, email=_unique_email("logout"))
    headers = {"Authorization": f"Bearer {signup['session_token']}"}

    logout_response = await client.post("/v1/auth/logout", headers=headers)

    assert logout_response.status_code == 204, logout_response.text
    me_response = await client.get("/v1/auth/me", headers=headers)
    assert me_response.status_code == 401, me_response.text


async def test_logout_requires_a_valid_session(client: AsyncClient) -> None:
    response = await client.post("/v1/auth/logout")

    assert response.status_code == 401, response.text


async def test_user_session_cannot_write_context_as_an_agent(client: AsyncClient) -> None:
    signup = await _signup(client, email=_unique_email("session-boundary"))

    response = await client.post(
        f"/v1/projects/{signup['project_id']}/context",
        headers={"Authorization": f"Bearer {signup['session_token']}"},
        json={
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "A user session must not become context provenance.",
            "version": 1,
        },
    )

    assert response.status_code == 401, response.text


async def test_web_signup_uses_httponly_cookie_without_exposing_session_token(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": _unique_email("web-cookie"),
            "password": PASSWORD,
            "display_name": "Web User",
            "client_kind": "web",
        },
    )

    assert response.status_code == 201, response.text
    assert "session_token" not in response.json()
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get("/v1/auth/me")).status_code == 200
