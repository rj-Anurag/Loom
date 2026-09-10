"""Contracts for Google-backed Loom accounts and client boundaries."""

from __future__ import annotations

import uuid
from dataclasses import replace

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.routers import auth as auth_router
from loom.config import settings
from loom.models import User
from loom.services.accounts.google import GoogleIdentity


def _identity(label: str = "google") -> GoogleIdentity:
    return GoogleIdentity(
        sub=f"{label}-{uuid.uuid4()}",
        email=f"{label}-{uuid.uuid4()}@example.com",
        email_verified=True,
        display_name="Google User",
        avatar_url="https://example.com/avatar.png",
    )


async def _exchange(
    client: AsyncClient,
    monkeypatch,
    identity: GoogleIdentity,
    *,
    client_kind: str = "extension",
):
    async def fake_verify(_request):
        return identity

    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(auth_router, "verify_google_exchange", fake_verify)
    return await client.post(
        "/v1/auth/google/exchange",
        json={"client_kind": client_kind, "access_token": "google-access-token"},
    )


async def test_google_exchange_creates_account_without_project(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    identity = _identity("new-google")

    response = await _exchange(client, monkeypatch, identity)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["session_token"].startswith("loom_session_")
    assert data["projects"] == []
    assert data["user"]["email"] == identity.email
    assert data["user"]["google_connected"] is True
    user = (
        await db_session.execute(select(User).where(User.google_sub == identity.sub))
    ).scalar_one()
    assert user.email_verified is True
    assert user.avatar_url == identity.avatar_url


async def test_google_exchange_reuses_same_google_subject(
    client: AsyncClient,
    monkeypatch,
) -> None:
    identity = _identity("returning-google")

    first = await _exchange(client, monkeypatch, identity, client_kind="cli")
    second = await _exchange(client, monkeypatch, identity, client_kind="extension")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert first.json()["session_token"] != second.json()["session_token"]


async def test_google_exchange_respects_public_signup_setting(
    client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "public_signups_enabled", False)

    response = await _exchange(client, monkeypatch, _identity("disabled-signup"))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "PUBLIC_SIGNUPS_DISABLED"


async def test_google_email_change_cannot_take_another_users_address(
    client: AsyncClient,
    monkeypatch,
) -> None:
    first_identity = _identity("email-owner-one")
    second_identity = _identity("email-owner-two")
    assert (await _exchange(client, monkeypatch, first_identity)).status_code == 200
    assert (await _exchange(client, monkeypatch, second_identity)).status_code == 200

    response = await _exchange(
        client,
        monkeypatch,
        replace(first_identity, email=second_identity.email),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "GOOGLE_ACCOUNT_CONFLICT"


async def test_extension_session_cannot_create_projects(
    client: AsyncClient,
    monkeypatch,
) -> None:
    auth = await _exchange(client, monkeypatch, _identity("extension-boundary"))
    headers = {"Authorization": f"Bearer {auth.json()['session_token']}"}

    response = await client.post(
        "/v1/projects",
        headers=headers,
        json={"name": "Must come from CLI", "client_kind": "extension"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "PROJECT_CREATION_NOT_ALLOWED"


async def test_google_config_reports_client_specific_setup(
    client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_cli_client_id", "cli.apps.googleusercontent.com")
    monkeypatch.setattr(
        settings,
        "google_extension_client_id",
        "extension.apps.googleusercontent.com",
    )

    cli = await client.get("/v1/auth/google/config", params={"client_kind": "cli"})
    extension = await client.get(
        "/v1/auth/google/config", params={"client_kind": "extension"}
    )

    assert cli.status_code == 200
    assert cli.json()["client_id"] == "cli.apps.googleusercontent.com"
    assert cli.json()["flow"] == "authorization_code_pkce"
    assert extension.json()["client_id"] == "extension.apps.googleusercontent.com"
    assert extension.json()["flow"] == "chrome_identity"
