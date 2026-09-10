"""Service layer for Project management endpoints.

Phase 1.11 — Browser Extension Core.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, ChatLink, ContextUnit, Project
from loom.security import generate_api_key, hash_api_key


async def list_projects(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Return only projects the caller is authorized to access."""
    statement = (
        select(Project)
        .where(Project.name != "__loom_extension__")
        .order_by(Project.created_at.desc())
    )
    if project_id is not None:
        statement = statement.where(Project.id == project_id)
    result = await session.execute(statement)
    projects = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in projects
    ]


async def get_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    """Return a single project by ID."""
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise ValueError("PROJECT_NOT_FOUND")
    context_count = await session.scalar(
        select(func.count(ContextUnit.id)).where(ContextUnit.project_id == project_id)
    )
    agent_count = await session.scalar(
        select(func.count(Agent.id)).where(Agent.project_id == project_id)
    )
    chat_count = await session.scalar(
        select(func.count(ChatLink.id)).where(ChatLink.project_id == project_id)
    )
    return {
        "id": str(project.id),
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "context_unit_count": context_count or 0,
        "agent_count": agent_count or 0,
        "linked_chat_count": chat_count or 0,
    }


async def create_project(
    session: AsyncSession,
    name: str,
    *,
    agent_kind: str = "browser",
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Create a project and its requested initial client agent.

    Returns the project details plus the agent credentials the extension
    should use for API calls.
    """
    project = Project(name=name)
    session.add(project)
    await session.flush()

    # Auto-create a browser-kind agent for the extension to use
    agent = Agent(project_id=project.id, kind=agent_kind, name=agent_name)
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
