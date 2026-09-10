"""Google OAuth verification for Loom's public account boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from loom.config import settings

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = ("openid", "email", "profile")


class GoogleAuthError(ValueError):
    """Stable public Google authentication error code."""


class GoogleExchangeInput(Protocol):
    @property
    def client_kind(self) -> str: ...

    @property
    def code(self) -> str | None: ...

    @property
    def id_token(self) -> str | None: ...

    @property
    def access_token(self) -> str | None: ...

    @property
    def redirect_uri(self) -> str | None: ...

    @property
    def code_verifier(self) -> str | None: ...


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    display_name: str
    avatar_url: str | None = None


def client_id_for(client_kind: str) -> str:
    return {
        "cli": settings.google_cli_client_id,
        "extension": settings.google_extension_client_id,
        "web": settings.google_web_client_id,
    }.get(client_kind, "")


def _identity_from_claims(claims: dict[str, Any]) -> GoogleIdentity:
    sub = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip()
    verified = claims.get("email_verified") in {True, "true", "True", "1", 1}
    if not sub or not email or not verified:
        raise GoogleAuthError("GOOGLE_EMAIL_NOT_VERIFIED")
    return GoogleIdentity(
        sub=sub,
        email=email,
        email_verified=True,
        display_name=str(claims.get("name") or email.split("@", 1)[0]).strip(),
        avatar_url=str(claims["picture"]).strip() if claims.get("picture") else None,
    )


async def _verify_id_token(token: str, audience: str) -> GoogleIdentity:
    def verify() -> dict[str, Any]:
        request = google_requests.Request()
        claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token,
            request,
            audience,
            clock_skew_in_seconds=10,
        )
        return cast(dict[str, Any], claims)

    try:
        claims = await asyncio.to_thread(verify)
    except Exception as exc:
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL") from exc
    return _identity_from_claims(claims)


async def _verify_access_token(token: str, audience: str) -> GoogleIdentity:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response, user_response = await asyncio.gather(
                client.get(GOOGLE_TOKENINFO_ENDPOINT, params={"access_token": token}),
                client.get(
                    GOOGLE_USERINFO_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                ),
            )
    except httpx.HTTPError as exc:
        raise GoogleAuthError("GOOGLE_AUTH_UNAVAILABLE") from exc
    if token_response.status_code != 200 or user_response.status_code != 200:
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL")
    token_data = cast(dict[str, Any], token_response.json())
    token_audience = str(token_data.get("audience") or token_data.get("aud") or "")
    try:
        expires_in = int(token_data.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if token_audience != audience or expires_in <= 0:
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL")
    claims = cast(dict[str, Any], user_response.json())
    token_subject = str(token_data.get("user_id") or token_data.get("sub") or "")
    if token_subject and token_subject != str(claims.get("sub") or ""):
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL")
    return _identity_from_claims(claims)


async def _exchange_code(exchange: GoogleExchangeInput, client_id: str) -> str:
    if not exchange.code_verifier or not exchange.redirect_uri:
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE")
    try:
        redirect = urlsplit(exchange.redirect_uri)
        port = redirect.port
    except ValueError as exc:
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE") from exc
    if (
        redirect.scheme != "http"
        or redirect.hostname != "127.0.0.1"
        or port is None
        or redirect.username is not None
        or redirect.password is not None
        or redirect.path != "/oauth/callback"
        or redirect.query
        or redirect.fragment
    ):
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE")
    payload = {
        "client_id": client_id,
        "code": exchange.code,
        "code_verifier": exchange.code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": exchange.redirect_uri,
    }
    if exchange.client_kind == "cli" and settings.google_cli_client_secret:
        payload["client_secret"] = settings.google_cli_client_secret
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
    except httpx.HTTPError as exc:
        raise GoogleAuthError("GOOGLE_AUTH_UNAVAILABLE") from exc
    if response.status_code != 200:
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL")
    token = str(response.json().get("id_token") or "")
    if not token:
        raise GoogleAuthError("INVALID_GOOGLE_CREDENTIAL")
    return token


async def verify_google_exchange(exchange: GoogleExchangeInput) -> GoogleIdentity:
    """Verify a client credential and return only durable Google identity claims."""

    if not settings.google_oauth_enabled:
        raise GoogleAuthError("GOOGLE_AUTH_DISABLED")
    client_id = client_id_for(exchange.client_kind)
    if not client_id:
        raise GoogleAuthError("GOOGLE_AUTH_NOT_CONFIGURED")
    supplied = sum(
        bool(value) for value in (exchange.code, exchange.id_token, exchange.access_token)
    )
    if supplied != 1:
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE")
    expected_credential = {
        "cli": bool(exchange.code),
        "web": bool(exchange.id_token),
        "extension": bool(exchange.access_token),
    }
    if not expected_credential.get(exchange.client_kind, False):
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE")
    if exchange.code:
        token = await _exchange_code(exchange, client_id)
        return await _verify_id_token(token, client_id)
    if exchange.id_token:
        return await _verify_id_token(exchange.id_token, client_id)
    if not exchange.access_token:
        raise GoogleAuthError("INVALID_GOOGLE_EXCHANGE")
    return await _verify_access_token(exchange.access_token, client_id)
