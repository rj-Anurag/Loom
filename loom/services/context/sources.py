"""Project-scoped source removal without mutating the append-only event log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import ContextUnit, Project
from loom.models.chat_links import ChatLink
from loom.services.context.provenance import SOURCE_TYPES


async def source_is_removed(
    session: AsyncSession,
    project_id: uuid.UUID,
    source_type: str,
    source_url: str | None,
    source_session_id: str | None,
    agent_id: uuid.UUID,
) -> bool:
    from loom.services.context.service import _normalize_source_url

    url = _normalize_source_url(source_url) if source_type == "browser_chat" else ""
    result = await session.execute(
        text(
            "SELECT 1 FROM removed_sources WHERE project_id = :project_id "
            "AND source_type = :source_type AND source_url = :source_url "
            "AND source_session_id = :source_session_id "
            "AND (agent_id IS NULL OR agent_id = :agent_id) LIMIT 1"
        ),
        {
            "project_id": project_id,
            "source_type": source_type,
            "source_url": url or "",
            "source_session_id": "" if url else source_session_id or "",
            "agent_id": agent_id,
        },
    )
    return result.first() is not None


async def remove_dependent_summaries(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Exclude summaries derived from removed evidence, including summary chains."""
    await session.execute(
        text(
            "WITH RECURSIVE affected(id) AS ("
            " SELECT id FROM context_units WHERE project_id = :project_id "
            " AND removed_at IS NOT NULL"
            " UNION"
            " SELECT e.child_id FROM context_edges e JOIN affected a ON e.parent_id = a.id"
            " JOIN context_units child ON child.id = e.child_id"
            " WHERE child.project_id = :project_id"
            " AND e.relation IN ('derived_from', 'supersedes', 'merged_from')"
            ") UPDATE context_units SET removed_at = now()"
            " WHERE project_id = :project_id AND type = 'summary'"
            " AND id IN (SELECT id FROM affected) AND removed_at IS NULL"
        ),
        {"project_id": project_id},
    )


async def remove_source(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    source_type: str,
    source_url: str | None = None,
    source_session_id: str | None = None,
    agent_id: uuid.UUID | None = None,
) -> int:
    """Exclude one sidebar source and prevent future capture under its identity."""
    from loom.services.context.service import _normalize_source_url

    if source_type not in SOURCE_TYPES:
        raise ValueError("INVALID_SOURCE_TYPE")
    # Writers hold a shared project lock until commit, so capture cannot race deletion.
    if await session.get(Project, project_id, with_for_update=True) is None:
        raise ValueError("PROJECT_NOT_FOUND")
    if source_type == "browser_chat" and source_url:
        url = _normalize_source_url(source_url)
        source_session_id = None
        agent_id = None
    else:
        url = None
        if agent_id is None:
            raise ValueError("AGENT_ID_REQUIRED")

    statement = select(ContextUnit).where(
        ContextUnit.project_id == project_id,
        ContextUnit.source_type == source_type,
        ContextUnit.removed_at.is_(None),
    )
    if not url:
        statement = statement.where(
            ContextUnit.agent_id == agent_id,
            ContextUnit.source_session_id == source_session_id,
        )
    rows = (await session.execute(statement)).scalars().all()
    matching = [
        unit for unit in rows
        if (
            _normalize_source_url(unit.source_url) == url
            if url
            else (
                unit.source_session_id == source_session_id
                and unit.agent_id == agent_id
                and (source_type != "browser_chat" or not unit.source_url)
            )
        )
    ]
    links: list[ChatLink] = []
    if url:
        candidates = (await session.execute(
            select(ChatLink).where(ChatLink.project_id == project_id, ChatLink.removed_at.is_(None))
        )).scalars().all()
        links = [link for link in candidates if _normalize_source_url(link.chat_url) == url]
    if not matching and not links:
        raise ValueError("SOURCE_NOT_FOUND")

    now = datetime.now(UTC)
    for unit in matching:
        unit.removed_at = now
    for link in links:
        link.removed_at = now
    await session.execute(
        text(
            "INSERT INTO removed_sources "
            "(project_id, source_type, source_url, source_session_id, agent_id) "
            "VALUES (:project_id, :source_type, :source_url, :source_session_id, :agent_id) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "project_id": project_id,
            "source_type": source_type,
            "source_url": url or "",
            "source_session_id": source_session_id or "",
            "agent_id": agent_id,
        },
    )
    await session.flush()
    await remove_dependent_summaries(session, project_id)
    await session.execute(
        text("DELETE FROM project_summaries WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    await session.commit()
    return len(matching)
