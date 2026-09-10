"""Client-bound validation for Google OAuth exchanges."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from loom.config import settings
from loom.services.accounts.google import GoogleAuthError, verify_google_exchange


@pytest.mark.parametrize(
    ("client_kind", "credential"),
    [
        ("cli", {"id_token": "unexpected-id-token"}),
        ("cli", {"access_token": "unexpected-access-token"}),
        ("web", {"code": "unexpected-code"}),
        ("web", {"access_token": "unexpected-access-token"}),
        ("extension", {"code": "unexpected-code"}),
        ("extension", {"id_token": "unexpected-id-token"}),
    ],
)
async def test_google_exchange_rejects_credentials_from_another_client_flow(
    monkeypatch: pytest.MonkeyPatch,
    client_kind: str,
    credential: dict[str, str],
) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_cli_client_id", "cli.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_web_client_id", "web.apps.googleusercontent.com")
    monkeypatch.setattr(
        settings,
        "google_extension_client_id",
        "extension.apps.googleusercontent.com",
    )
    fields: dict[str, str | None] = {
        "client_kind": client_kind,
        "code": None,
        "id_token": None,
        "access_token": None,
        "redirect_uri": None,
        "code_verifier": None,
    }
    fields.update(credential)
    exchange = SimpleNamespace(**fields)

    with pytest.raises(GoogleAuthError, match="INVALID_GOOGLE_EXCHANGE"):
        await verify_google_exchange(exchange)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://example.com/oauth/callback",
        "http://localhost:8080/oauth/callback",
        "http://127.0.0.1:8080/another-path",
        "http://user@127.0.0.1:8080/oauth/callback",
    ],
)
async def test_cli_exchange_accepts_only_exact_loopback_redirect_shape(
    monkeypatch: pytest.MonkeyPatch,
    redirect_uri: str,
) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_cli_client_id", "cli.apps.googleusercontent.com")
    exchange = SimpleNamespace(
        client_kind="cli",
        code="authorization-code",
        id_token=None,
        access_token=None,
        redirect_uri=redirect_uri,
        code_verifier="v" * 64,
    )

    with pytest.raises(GoogleAuthError, match="INVALID_GOOGLE_EXCHANGE"):
        await verify_google_exchange(exchange)
