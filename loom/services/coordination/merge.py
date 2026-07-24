"""Merge detection and resolution logic for concurrent context writes.

Provides entity-extraction-based overlap detection (v1 heuristic) and
auto-merge orchestration for non-overlapping concurrent writes.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import (
    ContextEdge,
    ContextUnit,
    ContextUnitType,
    EdgeRelation,
    EventLog,
    EventType,
    TrustTier,
)


# ── Entity extraction (v1 heuristic) ──────────────────────────────────────────


_ENTITY_PATTERNS = [
    # File paths: src/foo.py, lib/bar/baz.rs, app/models/user.rb
    r'(?:src|lib|app|tests|docs|config|scripts)[/\w.-]+\.\w{1,4}',
    # Function/method/class declarations
    r'(?:def|class|async def)\s+(\w+)',
    # Module/import references
    r'(?:import|from)\s+([\w.]+)',
    # URLs
    r'https?://\S+',
]


def extract_entities(content: str) -> set[str]:
    """Extract key entities from content text.

    Returns a set of file paths, function names, import references, and
    URLs mentioned in the text.  Used to detect content overlap between
    concurrent writes.
    """
    entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        entities.update(re.findall(pattern, content, re.IGNORECASE))
    return entities


def detect_overlap(content_a: str, content_b: str) -> bool:
    """Return ``True`` if two text contents mention the same entities.

    Uses simple set intersection on extracted entities (file paths,
    function names, imports, URLs).

    Parameters
    ----------
    content_a, content_b : str
        Text content of two context units.

    Returns
    -------
    bool
        ``True`` if the two texts share at least one entity.
    """
    entities_a = extract_entities(content_a)
    entities_b = extract_entities(content_b)
    return bool(entities_a & entities_b)


# ── Auto-merge ────────────────────────────────────────────────────────────────


async def auto_merge(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    new_unit_id: uuid.UUID,
    parent_ids: list[uuid.UUID],
) -> ContextUnit | None:
    """Auto-merge a new context unit with its siblings under the same parent.

    Creates a ``summary``-type merge unit that is a child of both the new
    unit and all existing children of the given parents (via ``merged_from``
    edges).  Appends a ``merge`` event to the event log.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy session (must be in an open transaction).
    project_id : uuid.UUID
        Target project.
    new_unit_id : uuid.UUID
        The newly created context unit to merge.
    parent_ids : list[uuid.UUID]
        Parent context-unit IDs that both the new unit and its siblings
        share.

    Returns
    -------
    ContextUnit
        The created merge unit.
    """
    # Find sibling children of the same parents (excluding the new unit)
    siblings = (
        await session.execute(
            select(ContextUnit).where(
                ContextUnit.id.in_(
                    select(ContextEdge.child_id).where(
                        ContextEdge.parent_id.in_(parent_ids),
                        ContextEdge.relation == EdgeRelation.derived_from,
                        ContextEdge.child_id != new_unit_id,
                    )
                )
            )
        )
    ).scalars().all()

    if not siblings:
        return None  # no siblings to merge with

    # Build a human-readable merge summary
    sibling_contents = [s.content for s in siblings]
    merge_content = _build_merge_content(sibling_contents)

    merge_unit = ContextUnit(
        project_id=project_id,
        agent_id=agent_id,
        client_uuid=uuid.uuid4(),
        type=ContextUnitType.summary,
        trust_tier=TrustTier.agent,
        content=merge_content,
        version=1,
    )
    session.add(merge_unit)
    await session.flush()

    # Create merged_from edges from each sibling → merge_unit
    all_child_ids = [s.id for s in siblings] + [new_unit_id]
    for child_id in all_child_ids:
        session.add(
            ContextEdge(
                parent_id=child_id,
                child_id=merge_unit.id,
                relation=EdgeRelation.merged_from,
            )
        )

    # Append merge event
    session.add(
        EventLog(
            project_id=project_id,
            event_type=EventType.merge,
            payload={
                "merge_unit_id": str(merge_unit.id),
                "child_ids": [str(cid) for cid in all_child_ids],
            },
        )
    )

    return merge_unit


def _build_merge_content(sibling_contents: list[str]) -> str:
    """Build a human-readable summary for the merge unit."""
    if len(sibling_contents) == 1:
        return f"Auto-merged: {sibling_contents[0][:100]}"
    return (
        f"Auto-merged {len(sibling_contents) + 1} concurrent writes: "
        + "; ".join(c[:60] for c in sibling_contents)
    )
