from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project
from loom.security import generate_api_key, hash_api_key

EXTENSION_CHAT_LINK_NAME = "__loom_extension__"


async def setup_extension(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(
        select(Project).where(Project.name == EXTENSION_CHAT_LINK_NAME)
    )
    # Old development builds allowed duplicate bootstrap rows. Select one
    # deterministically so upgrades remain usable instead of crashing setup.
    project = result.scalars().first()

    if project is None:
        project = Project(name=EXTENSION_CHAT_LINK_NAME)
        session.add(project)
        await session.flush()

        agent = Agent(
            project_id=project.id,
            kind="system",
            name="Loom Bootstrap",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        api_key = generate_api_key()
        agent.credentials_ref = hash_api_key(api_key)
        session.add(agent)
        await session.flush()
        await session.refresh(project)
        await session.commit()

        return {
            "id": str(project.id),
            "name": project.name,
            "created_at": project.created_at.isoformat() if project.created_at else "",
            "agent_id": str(agent.id),
            "api_key": api_key,
        }

    # Each setup gets a separate short-lived bootstrap identity, so parallel
    # onboarding flows cannot invalidate one another.
    agent = Agent(
        project_id=project.id,
        kind="system",
        name="Loom Bootstrap",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    api_key = generate_api_key()
    agent.credentials_ref = hash_api_key(api_key)
    session.add(agent)
    await session.flush()
    await session.refresh(agent)
    await session.commit()

    return {
        "id": str(project.id),
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "agent_id": str(agent.id),
        "api_key": api_key,
    }
