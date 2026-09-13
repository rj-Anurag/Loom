"""Public Google auth, login fallback, session, and account endpoints."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import UserAuthContext, require_user_auth
from loom.api.dependencies import get_redis
from loom.config import settings
from loom.db import get_session
from loom.models import User, UserSession
from loom.services.accounts.google import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_SCOPES,
    GoogleAuthError,
    client_id_for,
    verify_google_exchange,
)
from loom.services.accounts.rate_limit import (
    RateLimitExceededError,
    RateLimitUnavailableError,
    enforce_rate_limit,
)
from loom.services.accounts.service import (
    AccountError,
    exchange_user_session,
    google_login,
    issue_user_session,
    list_user_projects,
    login,
    revoke_session,
)

router = APIRouter(prefix="/v1/auth")


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)
    client_kind: Literal["web", "cli", "extension"] = "web"


class GoogleExchangeRequest(BaseModel):
    client_kind: Literal["web", "cli", "extension"]
    code: str | None = Field(None, min_length=1, max_length=4096)
    id_token: str | None = Field(None, min_length=1, max_length=8192)
    access_token: str | None = Field(None, min_length=1, max_length=8192)
    redirect_uri: str | None = Field(None, min_length=1, max_length=2048)
    code_verifier: str | None = Field(None, min_length=43, max_length=128)

    @model_validator(mode="after")
    def validate_exchange(self) -> GoogleExchangeRequest:
        if sum(bool(value) for value in (self.code, self.id_token, self.access_token)) != 1:
            raise ValueError("Provide exactly one Google credential")
        return self


class DashboardSessionResponse(BaseModel):
    path: str


class DashboardSessionConsumeRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)


def _set_web_session_cookie(response: Response, token: str, client_kind: str) -> None:
    if client_kind != "web":
        return
    response.set_cookie(
        "loom_session",
        token,
        max_age=settings.user_session_ttl_days * 86400,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


async def _enforce_auth_rate_limit(
    redis: redis_async.Redis | None,
    *,
    operation: str,
    identifier: str,
) -> None:
    try:
        await enforce_rate_limit(redis, operation=operation, identifier=identifier)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="TOO_MANY_ATTEMPTS",
            headers={"Retry-After": str(settings.auth_rate_limit_window_seconds)},
        ) from exc
    except RateLimitUnavailableError as exc:
        raise HTTPException(status_code=503, detail="AUTH_SERVICE_UNAVAILABLE") from exc


def _account_http_error(exc: AccountError) -> HTTPException:
    code = str(exc)
    statuses = {
        "INVALID_EMAIL": 422,
        "INVALID_CREDENTIALS": 401,
        "PUBLIC_ACCOUNT_CREATION_DISABLED": 403,
        "EMAIL_PASSWORD_AUTH_DISABLED": 403,
        "GOOGLE_ACCOUNT_CONFLICT": 409,
    }
    return HTTPException(status_code=statuses.get(code, 400), detail=code)


def _google_http_error(exc: GoogleAuthError) -> HTTPException:
    code = str(exc)
    statuses = {
        "GOOGLE_AUTH_DISABLED": 503,
        "GOOGLE_AUTH_NOT_CONFIGURED": 503,
        "GOOGLE_AUTH_UNAVAILABLE": 503,
        "INVALID_GOOGLE_CREDENTIAL": 401,
        "GOOGLE_EMAIL_NOT_VERIFIED": 403,
        "INVALID_GOOGLE_EXCHANGE": 422,
    }
    return HTTPException(status_code=statuses.get(code, 400), detail=code)


@router.get("/google/config")
async def google_config(
    client_kind: Literal["web", "cli", "extension"],
) -> dict[str, Any]:
    """Return public OAuth metadata; client secrets are never exposed."""

    client_id = client_id_for(client_kind)
    return {
        "enabled": settings.google_oauth_enabled and bool(client_id),
        "client_id": client_id,
        "authorization_endpoint": GOOGLE_AUTHORIZATION_ENDPOINT,
        "scopes": list(GOOGLE_SCOPES),
        "flow": "authorization_code_pkce"
        if client_kind == "cli"
        else ("chrome_identity" if client_kind == "extension" else "google_identity_services"),
    }


@router.post("/google/exchange")
async def google_exchange_endpoint(
    body: GoogleExchangeRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Verify Google once, then issue a revocable Loom session."""

    await _enforce_auth_rate_limit(
        redis,
        operation="google-auth-ip",
        identifier=request.client.host if request.client else "unknown",
    )
    try:
        identity = await verify_google_exchange(body)
        data = await google_login(
            session,
            identity=identity,
            client_kind=body.client_kind,
        )
    except GoogleAuthError as exc:
        raise _google_http_error(exc) from exc
    except AccountError as exc:
        raise _account_http_error(exc) from exc
    _set_web_session_cookie(response, data["session_token"], body.client_kind)
    response.headers["Cache-Control"] = "no-store"
    if body.client_kind == "web":
        data.pop("session_token", None)
    return data


@router.post("/dashboard-session")
async def create_dashboard_session_endpoint(
    response: Response,
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> DashboardSessionResponse:
    """Create a browser dashboard session from an authenticated extension session."""

    if auth.client_kind != "extension":
        raise HTTPException(status_code=403, detail="DASHBOARD_HANDOFF_NOT_ALLOWED")
    _, token = await issue_user_session(
        session,
        user_id=auth.user_id,
        client_kind="web",
        lifetime=timedelta(minutes=5),
    )
    response.headers["Cache-Control"] = "no-store"
    return DashboardSessionResponse(path=f"/v1/dashboard#handoff={token}")


async def _consume_dashboard_session(token: str, session: AsyncSession) -> str:
    try:
        return await exchange_user_session(
            session,
            token=token,
            expected_client_kind="web",
            new_client_kind="web",
        )
    except AccountError as exc:
        raise HTTPException(status_code=401, detail="Invalid dashboard session") from exc


@router.post("/dashboard-session/consume", status_code=204)
async def consume_dashboard_session_cookie_endpoint(
    body: DashboardSessionConsumeRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Exchange a dashboard fragment token for a first-party browser cookie."""

    cookie_token = await _consume_dashboard_session(body.token, session)
    _set_web_session_cookie(response, cookie_token, "web")
    response.headers["Cache-Control"] = "no-store"


@router.get("/dashboard-session/{token}")
async def consume_dashboard_session_endpoint(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Set the dashboard cookie, then leave the handoff URL behind."""

    cookie_token = await _consume_dashboard_session(token, session)
    redirect = RedirectResponse(url="/v1/dashboard", status_code=303)
    _set_web_session_cookie(redirect, cookie_token, "web")
    redirect.headers["Cache-Control"] = "no-store"
    return redirect


@router.post("/login")
async def login_endpoint(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Authenticate without revealing whether an email exists."""

    await _enforce_auth_rate_limit(
        redis,
        operation="login-ip",
        identifier=request.client.host if request.client else "unknown",
    )
    await _enforce_auth_rate_limit(
        redis,
        operation="login-email",
        identifier=body.email,
    )
    try:
        data = await login(
            session,
            email=body.email,
            password=body.password,
            client_kind=body.client_kind,
        )
        _set_web_session_cookie(response, data["session_token"], body.client_kind)
        response.headers["Cache-Control"] = "no-store"
        if body.client_kind == "web":
            data.pop("session_token", None)
        return data
    except AccountError as exc:
        raise _account_http_error(exc) from exc


@router.get("/me")
async def me_endpoint(
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await session.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "email_verified": user.email_verified,
        "google_connected": bool(user.google_sub),
        "projects": await list_user_projects(session, user.id),
    }


@router.post("/logout", status_code=204)
async def logout_endpoint(
    response: Response,
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_session = await session.get(UserSession, auth.session_id)
    if user_session is not None:
        await revoke_session(session, user_session)
    response.delete_cookie(
        "loom_session",
        path="/",
        secure=settings.environment == "production",
        httponly=True,
        samesite="lax",
    )
