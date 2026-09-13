"""Transactional account onboarding and project membership operations."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.models import Agent, Project, ProjectMembership, User, UserSession
from loom.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    password_hash_needs_upgrade,
    verify_password,
)
from loom.services.accounts.credentials import issue_agent_credential
from loom.services.accounts.google import GoogleIdentity

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_PASSWORD_HASH = hash_password("loom-dummy-password-for-timing-equality")


class AccountError(ValueError):
    """Stable public account error code."""


def normalize_email(value: str) -> str:
    """Normalize a login email and reject obviously invalid addresses."""

    normalized = value.strip().casefold()
    if len(normalized) > 320 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise AccountError("INVALID_EMAIL")
    return normalized


def _agent_kind(client_kind: str) -> str:
    return "local" if client_kind == "cli" else "browser"


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "email_verified": user.email_verified,
        "google_connected": bool(user.google_sub),
    }


def _project_payload(project: Project, role: str = "owner") -> dict[str, str]:
    return {
        "id": str(project.id),
        "name": project.name,
        "role": role,
        "created_at": project.created_at.isoformat() if project.created_at else "",
    }


async def _new_session(
    session: AsyncSession,
    user: User,
    client_kind: str,
    *,
    lifetime: timedelta | None = None,
) -> tuple[UserSession, str]:
    raw_token = generate_session_token()
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        client_kind=client_kind,
        expires_at=datetime.now(UTC) + (lifetime or timedelta(days=settings.user_session_ttl_days)),
    )
    session.add(user_session)
    await session.flush()
    return user_session, raw_token


async def issue_user_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    client_kind: str,
    lifetime: timedelta | None = None,
) -> tuple[UserSession, str]:
    """Issue another session for an already-authenticated user."""

    user = await session.get(User, user_id)
    if user is None or user.disabled_at is not None:
        raise AccountError("INVALID_CREDENTIALS")
    user_session, raw_session_token = await _new_session(
        session,
        user,
        client_kind,
        lifetime=lifetime,
    )
    await session.commit()
    return user_session, raw_session_token


async def exchange_user_session(
    session: AsyncSession,
    *,
    token: str,
    expected_client_kind: str,
    new_client_kind: str,
) -> str:
    """Atomically consume one session and replace it with a fresh session.

    This is used for browser handoffs so a token exposed to client-side URL
    handling is never retained as the long-lived cookie credential.
    """

    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_session_token(token))
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise AccountError("INVALID_SESSION_HANDOFF")
    old_session, user = row
    if (
        old_session.client_kind != expected_client_kind
        or old_session.revoked_at is not None
        or old_session.expires_at <= now
        or user.disabled_at is not None
    ):
        raise AccountError("INVALID_SESSION_HANDOFF")
    old_session.revoked_at = now
    _, replacement_token = await _new_session(session, user, new_client_kind)
    await session.commit()
    return replacement_token


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    client_kind: str,
) -> dict[str, Any]:
    """Verify credentials and issue a new revocable user session."""

    if not settings.email_password_auth_enabled:
        raise AccountError("EMAIL_PASSWORD_AUTH_DISABLED")
    try:
        normalized_email = normalize_email(email)
    except AccountError:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AccountError("INVALID_CREDENTIALS") from None

    user = (
        await session.execute(select(User).where(User.email == normalized_email))
    ).scalar_one_or_none()
    password_hash = (
        user.password_hash if user is not None and user.password_hash else _DUMMY_PASSWORD_HASH
    )
    password_valid = verify_password(password, password_hash)
    if user is None or not password_valid or user.disabled_at is not None:
        raise AccountError("INVALID_CREDENTIALS")
    if user.password_hash and password_hash_needs_upgrade(user.password_hash):
        user.password_hash = hash_password(password)

    user_session, raw_session_token = await _new_session(session, user, client_kind)
    await session.commit()
    projects = await list_user_projects(session, user.id)
    return {
        "user": _user_payload(user),
        "projects": projects,
        "session_token": raw_session_token,
        "session_expires_at": user_session.expires_at.isoformat(),
    }


async def google_login(
    session: AsyncSession,
    *,
    identity: GoogleIdentity,
    client_kind: str,
) -> dict[str, Any]:
    """Create or find a user by immutable Google subject and issue a Loom session."""

    normalized_email = normalize_email(identity.email)
    user = (
        await session.execute(select(User).where(User.google_sub == identity.sub))
    ).scalar_one_or_none()
    email_owner = (
        await session.execute(select(User).where(User.email == normalized_email))
    ).scalar_one_or_none()
    if user is not None and email_owner is not None and email_owner.id != user.id:
        raise AccountError("GOOGLE_ACCOUNT_CONFLICT")
    if user is None:
        user = email_owner
        if user is not None and user.google_sub not in {None, identity.sub}:
            raise AccountError("GOOGLE_ACCOUNT_CONFLICT")
        if user is None:
            if not settings.public_account_creation_enabled:
                raise AccountError("PUBLIC_ACCOUNT_CREATION_DISABLED")
            user = User(
                email=normalized_email,
                display_name=identity.display_name,
                password_hash=None,
                google_sub=identity.sub,
                email_verified=identity.email_verified,
                avatar_url=identity.avatar_url,
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                user = (
                    await session.execute(select(User).where(User.google_sub == identity.sub))
                ).scalar_one_or_none()
                if user is None:
                    raise AccountError("GOOGLE_ACCOUNT_CONFLICT") from exc
        else:
            user.google_sub = identity.sub

    if user.disabled_at is not None:
        raise AccountError("INVALID_CREDENTIALS")
    user.email = normalized_email
    user.email_verified = identity.email_verified
    user.display_name = identity.display_name or user.display_name
    user.avatar_url = identity.avatar_url
    user_session, raw_session_token = await _new_session(session, user, client_kind)
    await session.commit()
    return {
        "user": _user_payload(user),
        "projects": await list_user_projects(session, user.id),
        "session_token": raw_session_token,
        "session_expires_at": user_session.expires_at.isoformat(),
    }


async def list_user_projects(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict[str, str]]:
    """Return projects reachable through the user's memberships."""

    rows = (
        await session.execute(
            select(Project, ProjectMembership.role)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .where(ProjectMembership.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
    ).all()
    return [_project_payload(project, role) for project, role in rows]


async def get_membership(
    session: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ProjectMembership | None:
    return (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.project_id == project_id,
            )
        )
    ).scalar_one_or_none()


async def create_user_project(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    client_kind: str,
    client_name: str,
) -> dict[str, Any]:
    """Create another owned project and an initial client credential."""

    project = Project(name=name.strip())
    session.add(project)
    await session.flush()
    session.add(ProjectMembership(project_id=project.id, user_id=user_id, role="owner"))
    agent, raw_api_key = await issue_agent_credential(
        session,
        project_id=project.id,
        kind=_agent_kind(client_kind),
        name=client_name.strip(),
        created_by_user_id=user_id,
    )
    await session.commit()
    return {
        **_project_payload(project),
        "agent_id": str(agent.id),
        "api_key": raw_api_key,
    }


async def provision_agent(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    kind: str,
    name: str,
) -> tuple[Agent, str]:
    """Provision a project credential for an authorized account member."""

    membership = await get_membership(session, user_id, project_id)
    if membership is None:
        raise AccountError("PROJECT_NOT_FOUND")
    if membership.role not in {"owner", "admin"}:
        raise AccountError("INSUFFICIENT_ROLE")
    agent, raw_key = await issue_agent_credential(
        session,
        project_id=project_id,
        kind=kind,
        name=name,
        created_by_user_id=user_id,
    )
    await session.commit()
    return agent, raw_key


async def revoke_session(session: AsyncSession, user_session: UserSession) -> None:
    user_session.revoked_at = datetime.now(UTC)
    await session.commit()
