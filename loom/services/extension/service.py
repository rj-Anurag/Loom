from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


EXTENSION_CHAT_LINK_NAME = "__loom_extension__"


async def setup_extension(session: AsyncSession) -> dict:
    result = await session.execute(
        select(Project).where(Project.name == EXTENSION_CHAT_LINK_NAME)
    )
    project = result.scalar_one_or_none()

    if project is None:
        project = Project(name=EXTENSION_CHAT_LINK_NAME)
        session.add(project)
        await session.flush()

        agent = Agent(project_id=project.id, kind="browser")
        session.add(agent)
        await session.flush()
        await session.refresh(project)
        await session.commit()

        return {
            "id": str(project.id),
            "name": project.name,
            "created_at": project.created_at.isoformat() if project.created_at else "",
            "agent_id": str(agent.id),
            "api_key": str(agent.id),
        }

    result2 = await session.execute(
        select(Agent).where(
            Agent.project_id == project.id, Agent.kind == "browser"
        )
    )
    agent = result2.scalar_one_or_none()

    if agent is None:
        agent = Agent(project_id=project.id, kind="browser")
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
        await session.commit()

    return {
        "id": str(project.id),
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "agent_id": str(agent.id),
        "api_key": str(agent.id),
    }
