"""Service layer for chat-link management.

Phase 1.11 — Browser Extension Core.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models.agents import Agent
from loom.models.chat_links import ChatLink
from loom.models.projects import Project


async def link_chat(
    session: AsyncSession,
    project_id: str,
    chat_url: str,
    title: str = "",
    platform: str = "",
) -> dict:
    """Link a chat URL to a project.

    Idempotent: linking the same ``chat_url`` again returns the existing
    ``ChatLink`` record (no duplicate created).
    """
    # Verify the project exists
    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError("PROJECT_NOT_FOUND")

    # Get or create a browser agent for this project to ensure a valid api_key is returned
    agent_res = await session.execute(
        select(Agent).where(Agent.project_id == project.id, Agent.kind == "browser")
    )
    agent = agent_res.scalars().first()
    if agent is None:
        agent = Agent(project_id=project.id, kind="browser", name="Chrome Extension")
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
    api_key = str(agent.id)

    # Check if already linked (idempotent)
    result = await session.execute(
        select(ChatLink).where(ChatLink.chat_url == chat_url)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return {
            "id": str(existing.id),
            "project_id": str(existing.project_id),
            "chat_url": existing.chat_url,
            "title": existing.title,
            "platform": existing.platform,
            "linked_at": existing.linked_at.isoformat() if existing.linked_at else "",
            "api_key": api_key,
        }

    # Create the link
    link = ChatLink(
        project_id=project_id,
        chat_url=chat_url,
        title=title,
        platform=platform,
    )
    session.add(link)
    await session.flush()
    await session.refresh(link)
    await session.commit()

    return {
        "id": str(link.id),
        "project_id": str(link.project_id),
        "chat_url": link.chat_url,
        "title": link.title,
        "platform": link.platform,
        "linked_at": link.linked_at.isoformat() if link.linked_at else "",
        "api_key": api_key,
    }

