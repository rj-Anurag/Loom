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
    generate_api_key,
    generate_session_token,
    hash_api_key,
    hash_password,
    hash_session_token,
    password_hash_needs_upgrade,
    verify_password,
)

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


def _user_payload(user: User) -> dict[str, str]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
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
) -> tuple[UserSession, str]:
    raw_token = generate_session_token()
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        client_kind=client_kind,
        expires_at=datetime.now(UTC) + timedelta(days=settings.user_session_ttl_days),
    )
    session.add(user_session)
    await session.flush()
    return user_session, raw_token


async def _new_agent(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    kind: str,
    name: str,
    created_by_user_id: uuid.UUID,
) -> tuple[Agent, str]:
    raw_key = generate_api_key()
    agent = Agent(
        project_id=project_id,
        kind=kind,
        name=name,
        created_by_user_id=created_by_user_id,
        credentials_ref=hash_api_key(raw_key),
        key_hint=raw_key[-8:],
        expires_at=datetime.now(UTC) + timedelta(days=settings.agent_key_ttl_days),
    )
    session.add(agent)
    await session.flush()
    return agent, raw_key


async def signup(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    project_name: str,
    client_kind: str,
    client_name: str,
) -> dict[str, Any]:
    """Create user, first project, membership, client agent, and session atomically."""

    if not settings.public_signups_enabled:
        raise AccountError("PUBLIC_SIGNUPS_DISABLED")
    normalized_email = normalize_email(email)
    if await session.scalar(select(User.id).where(User.email == normalized_email)):
        raise AccountError("EMAIL_ALREADY_REGISTERED")

    user = User(
        email=normalized_email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    project = Project(name=project_name.strip())
    session.add_all((user, project))
    try:
        await session.flush()
        membership = ProjectMembership(project_id=project.id, user_id=user.id, role="owner")
        session.add(membership)
        agent, raw_api_key = await _new_agent(
            session,
            project.id,
            kind=_agent_kind(client_kind),
            name=client_name.strip(),
            created_by_user_id=user.id,
        )
        user_session, raw_session_token = await _new_session(session, user, client_kind)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AccountError("EMAIL_ALREADY_REGISTERED") from exc

    return {
        "user": _user_payload(user),
        "project": _project_payload(project),
        "project_id": str(project.id),
        "agent_id": str(agent.id),
        "project_api_key": raw_api_key,
        "session_token": raw_session_token,
        "session_expires_at": user_session.expires_at.isoformat(),
    }


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    client_kind: str,
) -> dict[str, Any]:
    """Verify credentials and issue a new revocable user session."""

    try:
        normalized_email = normalize_email(email)
    except AccountError:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AccountError("INVALID_CREDENTIALS") from None

    user = (
        await session.execute(select(User).where(User.email == normalized_email))
    ).scalar_one_or_none()
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, password_hash)
    if user is None or not password_valid or user.disabled_at is not None:
        raise AccountError("INVALID_CREDENTIALS")
    if password_hash_needs_upgrade(user.password_hash):
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
    agent, raw_api_key = await _new_agent(
        session,
        project.id,
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
    agent, raw_key = await _new_agent(
        session,
        project_id,
        kind=kind,
        name=name,
        created_by_user_id=user_id,
    )
    await session.commit()
    return agent, raw_key


async def revoke_session(session: AsyncSession, user_session: UserSession) -> None:
    user_session.revoked_at = datetime.now(UTC)
    await session.commit()
