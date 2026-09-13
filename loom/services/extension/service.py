from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Project
from loom.services.accounts.credentials import issue_agent_credential

EXTENSION_CHAT_LINK_NAME = "__loom_extension__"


async def setup_extension(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(select(Project).where(Project.name == EXTENSION_CHAT_LINK_NAME))
    # Old development builds allowed duplicate bootstrap rows. Select one
    # deterministically so upgrades remain usable instead of crashing setup.
    project = result.scalars().first()

    if project is None:
        project = Project(name=EXTENSION_CHAT_LINK_NAME)
        session.add(project)
        await session.flush()

        agent, api_key = await issue_agent_credential(
            session,
            project_id=project.id,
            kind="system",
            name="Loom Bootstrap",
            lifetime=timedelta(minutes=10),
        )
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
    agent, api_key = await issue_agent_credential(
        session,
        project_id=project.id,
        kind="system",
        name="Loom Bootstrap",
        lifetime=timedelta(minutes=10),
    )
    await session.refresh(agent)
    await session.commit()

    return {
        "id": str(project.id),
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "agent_id": str(agent.id),
        "api_key": api_key,
    }
