"""Contracts for Google-first account authentication."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.routers import auth as auth_router
from loom.config import settings
from loom.models import User
from loom.security import hash_password
from loom.services.accounts.google import GoogleIdentity

PASSWORD = "Correct-Horse-Battery-Staple-42!"


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4()}@example.com"


def _identity(label: str, *, display_name: str = "Google User") -> GoogleIdentity:
    return GoogleIdentity(
        sub=f"{label}-{uuid.uuid4()}",
        email=_unique_email(label),
        email_verified=True,
        display_name=display_name,
        avatar_url="https://example.com/avatar.png",
    )


async def _google_exchange(
    client: AsyncClient,
    monkeypatch,
    identity: GoogleIdentity,
    *,
    client_kind: str = "cli",
) -> dict[str, Any]:
    async def fake_verify(_request: object) -> GoogleIdentity:
        return identity

    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(auth_router, "verify_google_exchange", fake_verify)
    response = await client.post(
        "/v1/auth/google/exchange",
        json={
            "client_kind": client_kind,
            "id_token" if client_kind == "web" else "access_token": "google-token",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_email_password_signup_endpoint_is_not_exposed(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": _unique_email("removed-signup"),
            "password": PASSWORD,
            "display_name": "Removed Signup",
            "client_kind": "cli",
        },
    )

    assert response.status_code == 404, response.text


async def test_google_login_creates_account_session_without_project(
    client: AsyncClient,
    monkeypatch,
) -> None:
    identity = _identity("google-account", display_name="Ada Lovelace")

    data = await _google_exchange(client, monkeypatch, identity)

    assert data["session_token"].startswith("loom_session_")
    assert data["projects"] == []
    assert data["user"]["email"] == identity.email
    assert data["user"]["display_name"] == "Ada Lovelace"
    assert data["user"]["google_connected"] is True
    assert "project_api_key" not in data


async def test_login_returns_session_but_never_reissues_project_api_key(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = _unique_email("legacy-login")
    db_session.add(
        User(
            email=email,
            display_name="Margaret Hamilton",
            password_hash=hash_password(PASSWORD),
        )
    )
    await db_session.commit()

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


async def test_login_rejects_invalid_password(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = _unique_email("wrong-password")
    db_session.add(
        User(
            email=email,
            display_name="Wrong Password",
            password_hash=hash_password(PASSWORD),
        )
    )
    await db_session.commit()

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


async def test_me_returns_the_google_session_user(client: AsyncClient, monkeypatch) -> None:
    identity = _identity("me", display_name="Katherine Johnson")
    auth = await _google_exchange(client, monkeypatch, identity)

    response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {auth['session_token']}"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == auth["user"]["id"]
    assert data["email"] == identity.email
    assert data["display_name"] == "Katherine Johnson"
    assert "project_api_key" not in data


async def test_me_requires_a_valid_session(client: AsyncClient) -> None:
    response = await client.get("/v1/auth/me")

    assert response.status_code == 401, response.text


async def test_logout_revokes_the_current_session(client: AsyncClient, monkeypatch) -> None:
    auth = await _google_exchange(client, monkeypatch, _identity("logout"))
    headers = {"Authorization": f"Bearer {auth['session_token']}"}

    logout_response = await client.post("/v1/auth/logout", headers=headers)

    assert logout_response.status_code == 204, logout_response.text
    me_response = await client.get("/v1/auth/me", headers=headers)
    assert me_response.status_code == 401, me_response.text


async def test_logout_requires_a_valid_session(client: AsyncClient) -> None:
    response = await client.post("/v1/auth/logout")

    assert response.status_code == 401, response.text


async def test_user_session_cannot_write_context_as_an_agent(
    client: AsyncClient,
    monkeypatch,
) -> None:
    auth = await _google_exchange(client, monkeypatch, _identity("session-boundary"))
    session_headers = {"Authorization": f"Bearer {auth['session_token']}"}
    project_response = await client.post(
        "/v1/projects",
        headers=session_headers,
        json={
            "name": "Session Boundary",
            "client_kind": "cli",
            "client_name": "Loom CLI",
        },
    )
    assert project_response.status_code == 201, project_response.text

    response = await client.post(
        f"/v1/projects/{project_response.json()['id']}/context",
        headers=session_headers,
        json={
            "client_uuid": str(uuid.uuid4()),
            "type": "decision",
            "content": "A user session must not become context provenance.",
            "version": 1,
        },
    )

    assert response.status_code == 401, response.text


async def test_web_google_login_uses_httponly_cookie_without_exposing_session_token(
    client: AsyncClient,
    monkeypatch,
) -> None:
    async def fake_verify(_request: object) -> GoogleIdentity:
        return _identity("web-cookie", display_name="Web User")

    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(auth_router, "verify_google_exchange", fake_verify)
    response = await client.post(
        "/v1/auth/google/exchange",
        json={"client_kind": "web", "id_token": "google-token"},
    )

    assert response.status_code == 200, response.text
    assert "session_token" not in response.json()
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_extension_session_can_launch_web_dashboard(
    client: AsyncClient,
    monkeypatch,
) -> None:
    extension_auth = await _google_exchange(
        client,
        monkeypatch,
        _identity("dashboard-handoff", display_name="Dashboard User"),
        client_kind="extension",
    )

    launch_response = await client.post(
        "/v1/auth/dashboard-session",
        headers={"Authorization": f"Bearer {extension_auth['session_token']}"},
    )

    assert launch_response.status_code == 200, launch_response.text
    launch_path = launch_response.json()["path"]
    assert launch_path.startswith("/v1/dashboard#handoff=loom_session_")
    token = launch_path.removeprefix("/v1/dashboard#handoff=")

    consume_response = await client.post(
        "/v1/auth/dashboard-session/consume",
        json={"token": token},
    )

    assert consume_response.status_code == 204, consume_response.text
    assert "HttpOnly" in consume_response.headers["set-cookie"]
    assert "SameSite=lax" in consume_response.headers["set-cookie"]
    assert consume_response.headers["cache-control"] == "no-store"
    authenticated_response = await client.get("/v1/auth/me")
    assert authenticated_response.status_code == 200, authenticated_response.text
    assert authenticated_response.json()["display_name"] == "Dashboard User"

    # Keep the redirect endpoint for extension builds released before the
    # first-party fragment exchange was introduced.
    handoff_path = f"/v1/auth/dashboard-session/{token}"

    handoff_response = await client.get(handoff_path, follow_redirects=False)

    assert handoff_response.status_code == 303, handoff_response.text
    assert handoff_response.headers["location"] == "/v1/dashboard"
    assert "HttpOnly" in handoff_response.headers["set-cookie"]
    assert handoff_response.headers["cache-control"] == "no-store"
