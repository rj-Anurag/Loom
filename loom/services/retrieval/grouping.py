"""Deterministic time-window grouping of unsummarized context units.

Groups context units into aligned time windows and produces
:class:`SummarizationGroup` instances suitable for LLM summarization.

"Unsummarized" means a unit has **no incoming ``supersedes`` edge** — no
summary exists that supersedes it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SUMMARY_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "loom-summarization")
"""Namespace for deterministic summary client_uuid generation."""

_TRUST_TIER_ORDER: dict[str, int] = {
    "user": 3,
    "agent": 2,
    "external_tool": 1,
}


def _get_highest_tier(tiers: list[str]) -> str:
    """Return the highest-priority trust tier from the given list.

    Order (highest → lowest): ``"user"`` > ``"agent"`` > ``"external_tool"``.

    Parameters
    ----------
    tiers : list[str]
        Trust tier strings to evaluate.

    Returns
    -------
    str
        The highest tier present, or ``"agent"`` if the list is empty.
    """
    best: str = "agent"
    best_order: int = 0
    for t in tiers:
        order = _TRUST_TIER_ORDER.get(t, 0)
        if order > best_order:
            best = t
            best_order = order
    return best


@dataclass
class SummarizationGroup:
    """A group of unsummarized context units to be summarized together."""

    window_start: datetime  # Aligned time window boundary
    unit_ids: list[uuid.UUID]  # Sorted oldest-first
    contents: list[str]  # Corresponding content texts
    types: list[str]  # Corresponding unit types
    trust_tiers: list[str]  # Corresponding trust tiers
    agent_ids: list[uuid.UUID]  # Corresponding agent IDs
    created_ats: list[datetime]  # Corresponding timestamps
    highest_trust_tier: str  # Max trust tier from source units
    sorted_ids_string: str  # Sorted, comma-separated UUIDs for idempotency

    @property
    def summary_client_uuid(self) -> uuid.UUID:
        """Deterministic UUID for idempotent summary writes."""
        return uuid.uuid5(SUMMARY_NS, self.sorted_ids_string)


async def find_unsummarized_groups(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    window_minutes: int = 10,
    max_units_per_group: int = 50,
    min_units: int = 5,
) -> list[SummarizationGroup]:
    """Find and group unsummarized context units for a project.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    window_minutes : int
        Size of each time window in minutes.
    max_units_per_group : int
        Maximum units per group (oldest first).
    min_units : int
        Minimum units required to form a group.

    Returns
    -------
    list[SummarizationGroup]
        Groups ordered by window_start ascending (oldest first).
    """
    rows = (
        await session.execute(
            text(
                "SELECT u.id, u.content, u.type, u.trust_tier, u.agent_id, u.created_at "
                "FROM context_units u "
                "WHERE u.project_id = :project_id "
                "  AND u.id NOT IN ("
                "    SELECT e.parent_id FROM context_edges e "
                "    WHERE e.relation = 'supersedes'"
                "      AND e.parent_id IN ("
                "        SELECT cu.id FROM context_units cu WHERE cu.project_id = :project_id"
                "      )"
                "  ) "
                "ORDER BY u.created_at ASC"
            ),
            {"project_id": project_id},
        )
    ).mappings()

    # Group rows by aligned time window
    window_seconds = window_minutes * 60
    groups: dict[int, list[dict]] = {}

    for row in rows:
        created_at: datetime = row["created_at"]
        epoch = int(created_at.replace(tzinfo=timezone.utc).timestamp())
        aligned = (epoch // window_seconds) * window_seconds
        groups.setdefault(aligned, []).append(row)

    result: list[SummarizationGroup] = []
    for aligned_epoch in sorted(groups.keys()):
        group_rows = groups[aligned_epoch]

        # Skip groups below minimum threshold
        if len(group_rows) < min_units:
            continue

        # Truncate to max_units_per_group (oldest preserved since already sorted)
        group_rows = group_rows[:max_units_per_group]

        unit_ids = [row["id"] for row in group_rows]
        contents = [row["content"] for row in group_rows]
        types = [row["type"] for row in group_rows]
        trust_tiers = [row["trust_tier"] for row in group_rows]
        agent_ids = [row["agent_id"] for row in group_rows]
        created_ats = [row["created_at"] for row in group_rows]
        highest_trust_tier = _get_highest_tier(trust_tiers)
        sorted_ids_string = ",".join(str(uid) for uid in unit_ids)

        result.append(
            SummarizationGroup(
                window_start=datetime.fromtimestamp(aligned_epoch, tz=timezone.utc),
                unit_ids=unit_ids,
                contents=contents,
                types=types,
                trust_tiers=trust_tiers,
                agent_ids=agent_ids,
                created_ats=created_ats,
                highest_trust_tier=highest_trust_tier,
                sorted_ids_string=sorted_ids_string,
            )
        )

    return result


async def count_unsummarized(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> int:
    """Return the count of unsummarized units for a project.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.

    Returns
    -------
    int
        Number of unsummarized units.
    """
    row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM context_units u "
                "WHERE u.project_id = :project_id "
                "  AND u.id NOT IN ("
                "    SELECT e.parent_id FROM context_edges e "
                "    WHERE e.relation = 'supersedes'"
                "  )"
            ),
            {"project_id": project_id},
        )
    ).scalar()
    return row or 0
