"""Centralized issuance for project-scoped agent credentials."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.models import Agent
from loom.security import generate_api_key, hash_api_key


async def issue_agent_credential(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    kind: str,
    name: str | None,
    created_by_user_id: uuid.UUID | None = None,
    lifetime: timedelta | None = None,
) -> tuple[Agent, str]:
    """Create an agent and return its raw credential exactly once."""

    raw_key = generate_api_key()
    agent = Agent(
        project_id=project_id,
        kind=kind,
        name=name,
        created_by_user_id=created_by_user_id,
        credentials_ref=hash_api_key(raw_key),
        key_hint=raw_key[-8:],
        expires_at=datetime.now(UTC) + (lifetime or timedelta(days=settings.agent_key_ttl_days)),
    )
    session.add(agent)
    await session.flush()
    return agent, raw_key
