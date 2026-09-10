"""Authentication middleware for the Loom API.

Provides FastAPI dependencies that extract and verify bearer tokens,
and validate project-level access.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.db import get_session
from loom.models import Agent, User, UserSession
from loom.security import SESSION_TOKEN_PREFIX, hash_api_key, hash_session_token


class AuthContext:
    """Represents an authenticated agent."""

    def __init__(self, agent_id: uuid.UUID, project_id: uuid.UUID | None = None) -> None:
        self.agent_id = agent_id
        self.project_id = project_id


class UserAuthContext:
    """Represents an authenticated public user session."""

    def __init__(self, user_id: uuid.UUID, session_id: uuid.UUID, client_kind: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.client_kind = client_kind


class PrincipalContext:
    """User-or-agent identity accepted by administrative project endpoints."""

    def __init__(
        self,
        kind: Literal["agent", "user"],
        *,
        agent_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        client_kind: str | None = None,
    ) -> None:
        self.kind = kind
        self.agent_id = agent_id
        self.project_id = project_id
        self.user_id = user_id
        self.session_id = session_id
        self.client_kind = client_kind


def _extract_bearer_token(authorization: str | None, cookie_token: str | None = None) -> str:
    if not authorization and cookie_token:
        return cookie_token
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization scheme")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Malformed token")
    return token


async def _authenticate_agent(token: str, session: AsyncSession) -> Agent:
    agent = (
        await session.execute(
            select(Agent).where(
                Agent.credentials_ref == hash_api_key(token),
                Agent.revoked_at.is_(None),
                or_(Agent.expires_at.is_(None), Agent.expires_at > datetime.now(UTC)),
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
                and (candidate.expires_at is None or candidate.expires_at > datetime.now(UTC))
            ):
                agent = candidate
    if agent is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return agent


async def _authenticate_user(token: str, session: AsyncSession) -> tuple[UserSession, User]:
    if not token.startswith(SESSION_TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_session_token(token))
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_session, user = row
    if (
        user_session.revoked_at is not None
        or user_session.expires_at <= datetime.now(UTC)
        or user.disabled_at is not None
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
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
    agent = await _authenticate_agent(token, session)
    return AuthContext(agent_id=agent.id, project_id=agent.project_id)


async def require_user_auth(
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias="loom_session"),
    session: AsyncSession = Depends(get_session),
) -> UserAuthContext:
    """Validate an opaque, revocable public-user session token."""

    token = _extract_bearer_token(authorization, cookie_token)
    user_session, user = await _authenticate_user(token, session)
    return UserAuthContext(
        user_id=user.id,
        session_id=user_session.id,
        client_kind=user_session.client_kind,
    )


async def require_principal(
    authorization: str | None = Header(None),
    cookie_token: str | None = Cookie(None, alias="loom_session"),
    session: AsyncSession = Depends(get_session),
) -> PrincipalContext:
    """Authenticate a user session or legacy project-scoped agent key."""

    token = _extract_bearer_token(authorization, cookie_token)
    if token.startswith(SESSION_TOKEN_PREFIX):
        user_session, user = await _authenticate_user(token, session)
        return PrincipalContext(
            "user",
            user_id=user.id,
            session_id=user_session.id,
            client_kind=user_session.client_kind,
        )
    agent = await _authenticate_agent(token, session)
    return PrincipalContext(
        "agent", agent_id=agent.id, project_id=agent.project_id
    )
