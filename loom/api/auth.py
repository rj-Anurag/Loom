"""Authentication middleware for the Loom API.

Provides FastAPI dependencies that extract and verify bearer tokens,
and validate project-level access.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.db import get_session
from loom.models import Agent, ProjectMembership, User, UserSession
from loom.security import API_KEY_PREFIX, SESSION_TOKEN_PREFIX, hash_api_key, hash_session_token

_MAX_CREDENTIAL_LENGTH = 512
_ACTIVITY_WRITE_INTERVAL = timedelta(minutes=5)
_AUTHENTICATION_ERROR = HTTPException(
    status_code=401,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Represents an authenticated agent."""

    agent_id: uuid.UUID
    project_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UserAuthContext:
    """Represents an authenticated public user session."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    client_kind: str


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """User-or-agent identity accepted by administrative project endpoints."""

    kind: Literal["agent", "user"]
    agent_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    client_kind: str | None = None


class ProjectRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class ProjectAuthorization:
    """An authenticated human's authorization within one project."""

    user_id: uuid.UUID
    project_id: uuid.UUID
    role: ProjectRole
    session_id: uuid.UUID
    client_kind: str


def _authentication_error() -> HTTPException:
    """Return a fresh generic challenge without revealing credential state."""

    return HTTPException(
        status_code=_AUTHENTICATION_ERROR.status_code,
        detail=_AUTHENTICATION_ERROR.detail,
        headers=_AUTHENTICATION_ERROR.headers,
    )


def _extract_bearer_token(authorization: str | None, cookie_token: str | None = None) -> str:
    if not authorization:
        if not cookie_token:
            raise _authentication_error()
        token = cookie_token
    else:
        scheme, separator, token = authorization.partition(" ")
        token = token.strip()
        if scheme.casefold() != "bearer" or not separator or not token:
            raise _authentication_error()
    if any(character.isspace() for character in token) or len(token) > _MAX_CREDENTIAL_LENGTH:
        raise _authentication_error()
    return token


def _validate_cookie_request(request: Request, authorization: str | None) -> None:
    """Reject cross-site state changes authenticated only by a browser cookie."""

    if authorization or request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin not in settings.browser_origins:
        raise HTTPException(status_code=403, detail="UNTRUSTED_ORIGIN")


async def authenticate_agent(token: str, session: AsyncSession) -> Agent:
    now = datetime.now(UTC)
    agent = None
    if token.startswith(API_KEY_PREFIX):
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.credentials_ref == hash_api_key(token),
                    Agent.revoked_at.is_(None),
                    or_(Agent.expires_at.is_(None), Agent.expires_at > now),
                )
            )
        ).scalar_one_or_none()
    if agent is None and settings.allow_legacy_uuid_tokens:
        try:
            agent_id = uuid.UUID(token)
        except ValueError:
            agent_id = None
        if agent_id is not None:
            candidate = await session.get(Agent, agent_id)
            if (
                candidate is not None
                and candidate.revoked_at is None
                and (candidate.expires_at is None or candidate.expires_at > now)
            ):
                agent = candidate
    if agent is None:
        raise _authentication_error()
    if agent.last_used_at is None or agent.last_used_at <= now - _ACTIVITY_WRITE_INTERVAL:
        await session.execute(update(Agent).where(Agent.id == agent.id).values(last_used_at=now))
        await session.commit()
    return agent


async def _authenticate_user(token: str, session: AsyncSession) -> tuple[UserSession, User]:
    if not token.startswith(SESSION_TOKEN_PREFIX):
        raise _authentication_error()
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_session_token(token))
        )
    ).one_or_none()
    if row is None:
        raise _authentication_error()
    user_session, user = row
    if (
        user_session.revoked_at is not None
        or user_session.expires_at <= datetime.now(UTC)
        or user.disabled_at is not None
    ):
        raise _authentication_error()
    now = datetime.now(UTC)
    if (
        user_session.last_used_at is None
        or user_session.last_used_at <= now - _ACTIVITY_WRITE_INTERVAL
    ):
        user_session.last_used_at = now
        await session.commit()
    return user_session, user


async def require_auth(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """Extract and validate the Bearer token → Agent mapping.

    New agents use opaque bearer keys stored only as SHA-256 digests.
    Historical UUID-as-token credentials remain available only when the
    explicit migration switch is enabled. Returns 401 for missing, malformed,
    or unknown tokens.
    """
    token = _extract_bearer_token(authorization)
    if token.startswith(SESSION_TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="Agent credential required")
    agent = await authenticate_agent(token, session)
    return AuthContext(agent_id=agent.id, project_id=agent.project_id)


async def require_user_auth(
    request: Request,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias="loom_session"),
    session: AsyncSession = Depends(get_session),
) -> UserAuthContext:
    """Validate an opaque, revocable public-user session token."""

    token = _extract_bearer_token(authorization, cookie_token)
    if cookie_token and not authorization:
        _validate_cookie_request(request, authorization)
    user_session, user = await _authenticate_user(token, session)
    return UserAuthContext(
        user_id=user.id,
        session_id=user_session.id,
        client_kind=user_session.client_kind,
    )


async def require_principal(
    request: Request,
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias="loom_session"),
    session: AsyncSession = Depends(get_session),
) -> PrincipalContext:
    """Authenticate a user session or project-scoped agent key."""

    token = _extract_bearer_token(authorization, cookie_token)
    if cookie_token and not authorization:
        _validate_cookie_request(request, authorization)
    if token.startswith(SESSION_TOKEN_PREFIX):
        user_session, user = await _authenticate_user(token, session)
        return PrincipalContext(
            "user",
            user_id=user.id,
            session_id=user_session.id,
            client_kind=user_session.client_kind,
        )
    agent = await authenticate_agent(token, session)
    return PrincipalContext("agent", agent_id=agent.id, project_id=agent.project_id)


async def require_project_agent(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Authorize an agent against the project in the request path."""

    if auth.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return auth


async def require_project_agent_scope(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Reject an authenticated agent whose explicit project scope differs."""

    if auth.project_id != project_id:
        raise HTTPException(status_code=403, detail="AGENT_MISMATCH")
    return auth


async def require_matching_project_agent(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Authorize project-bound endpoints that expose a scope-mismatch error."""

    if auth.project_id != project_id:
        raise HTTPException(status_code=403, detail="PROJECT_MISMATCH")
    return auth


async def require_project_member(
    project_id: uuid.UUID,
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> ProjectAuthorization:
    """Authorize any human project member and retain their role."""

    membership = (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.user_id == auth.user_id,
                ProjectMembership.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return ProjectAuthorization(
        user_id=auth.user_id,
        project_id=project_id,
        role=ProjectRole(membership.role),
        session_id=auth.session_id,
        client_kind=auth.client_kind,
    )


async def require_project_admin(
    authorization: ProjectAuthorization = Depends(require_project_member),
) -> ProjectAuthorization:
    """Authorize roles allowed to manage project credentials."""

    if authorization.role not in {ProjectRole.OWNER, ProjectRole.ADMIN}:
        raise HTTPException(status_code=403, detail="INSUFFICIENT_ROLE")
    return authorization


async def require_project_principal(
    project_id: uuid.UUID,
    auth: PrincipalContext = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> PrincipalContext:
    """Authorize either supported principal type for one project."""

    if auth.kind == "agent":
        if auth.project_id != project_id:
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
        return auth
    membership = (
        await session.execute(
            select(ProjectMembership.id).where(
                ProjectMembership.user_id == auth.user_id,
                ProjectMembership.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return auth
