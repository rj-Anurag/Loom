"""Service layer for Project management endpoints.

Phase 1.11 — Browser Extension Core.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project


async def list_projects(session: AsyncSession) -> list[dict]:
    """Return all projects as a list of dicts."""
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in projects
    ]


async def create_project(
    session: AsyncSession,
    name: str,
) -> dict:
    """Create a project and a browser-kind agent for it.

    Returns the project details plus the agent credentials the extension
    should use for API calls.
    """
    project = Project(name=name)
    session.add(project)
    await session.flush()

    # Auto-create a browser-kind agent for the extension to use
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
        "api_key": str(agent.id),  # MVP: agent UUID = bearer token
    }
