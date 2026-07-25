"""Branch CRUD, lifecycle, and merge orchestration for the Coordination Service.

Provides branch creation, listing, and merge logic with conflict detection
by reusing the existing ``merge.py`` helpers (entity extraction, overlap
detection, auto-merge).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import redis.asyncio as redis_async
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Branch, ContextEdge, ContextUnit, EdgeRelation, EventLog, EventType, PendingBranch
from loom.services.coordination.locks import acquire_locks, release_lock

# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class MergeResult:
    """Result of a branch merge operation."""

    status: Literal["merged", "conflict", "nothing_to_merge"]
    merge_unit_id: str | None = None
    conflict_ids: list[str] = field(default_factory=list)


VALID_STATUSES = {"open", "merging", "merged", "abandoned"}


# ── Branch CRUD ───────────────────────────────────────────────────────────────


async def create_branch(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    agent_id: uuid.UUID,
    *,
    source_branch_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> Branch:
    """Create a new branch.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    name : str
        Human-readable branch name (must be unique per project).
    agent_id : uuid.UUID
        Creating agent.
    source_branch_id : uuid.UUID | None
        Optional source branch this branch derives from.
    task_id : uuid.UUID | None
        Optional task this branch is associated with.

    Returns
    -------
    Branch
        The newly created branch record.

    Raises
    ------
    ValueError
        With ``BRANCH_NAME_TAKEN`` if the name already exists for this project.
    """
    # Check for duplicate name
    existing = await session.execute(
        select(Branch).where(
            Branch.project_id == project_id,
            Branch.name == name,
            Branch.status.in_(["open", "merging"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("BRANCH_NAME_TAKEN")

    branch = Branch(
        project_id=project_id,
        name=name,
        status="open",
        source_branch_id=source_branch_id,
        created_by=agent_id,
        task_id=task_id,
    )
    session.add(branch)
    await session.commit()
    await session.refresh(branch)
    return branch


async def list_branches(
    session: AsyncSession,
    project_id: uuid.UUID,
    status: str | None = None,
) -> list[Branch]:
    """List branches for a project, optionally filtered by status."""
    query = select(Branch).where(Branch.project_id == project_id)
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"INVALID_STATUS: {status}")
        query = query.where(Branch.status == status)
    query = query.order_by(Branch.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_branch(
    session: AsyncSession,
    branch_id: uuid.UUID,
) -> Branch | None:
    """Get a single branch by ID."""
    return await session.get(Branch, branch_id)


# ── Merge logic ────────────────────────────────────────────────────────────────


async def merge_branch(
    session: AsyncSession,
    redis: redis_async.Redis | None,
    branch_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> MergeResult:
    """Merge a branch into main.

    1. Load the branch and validate it's mergeable.
    2. Acquire locks on all context units in the branch.
    3. For each unit, check conflict with existing children of the same parents.
    4. Non-overlapping → auto-merge using ``merge.py`` helpers.
    5. Overlapping → create ``PendingBranch`` with ``branch_id``.
    6. Update branch status to ``'merged'`` or leave open flagged with conflict.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    redis : redis_async.Redis | None
        Redis client for locking (may be None for optimistic mode).
    branch_id : uuid.UUID
        Branch to merge.
    agent_id : uuid.UUID
        Agent performing the merge.

    Returns
    -------
    MergeResult
        Status and details of the merge.
    """
    from loom.services.coordination.merge import detect_overlap

    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise ValueError("BRANCH_NOT_FOUND")

    if branch.status == "merged":
        return MergeResult(status="nothing_to_merge")

    if branch.status not in ("open", "merging"):
        raise ValueError(f"BRANCH_INVALID_STATUS: {branch.status}")

    # Mark as merging
    branch.status = "merging"
    await session.flush()

    # Find all context units on this branch
    # Units belong to a branch if their agent_id matches the branch creator
    # and they were created >= branch.created_at
    # (Simple heuristic: branch units are those with branch_id marker)
    # For Phase 2.1, we use a simpler approach: find context units whose
    # agent_id matches branch.created_by, within the project, created after
    # the branch was created.

    # Actually, the cleanest approach: context units have branch_id stored
    # as a marker. But we don't have schema changes for that yet.
    # Alternative: find all units with no parent that are on the branch,
    # or all units written by the branch's agent after branch creation.

    # For now, let's find units that were written by the branch's agent
    # for this project, after branch creation, that haven't been merged yet.
    branch_units = (
        await session.execute(
            select(ContextUnit).where(
                ContextUnit.project_id == branch.project_id,
                ContextUnit.agent_id == branch.created_by,
                ContextUnit.created_at >= branch.created_at,
            )
        )
    ).scalars().all()

    if not branch_units:
        # No units to merge
        branch.status = "merged"
        branch.merged_at = datetime.now(timezone.utc)
        await session.commit()
        return MergeResult(status="nothing_to_merge")

    # Acquire locks on all branch unit IDs
    unit_ids = [str(u.id) for u in branch_units]
    lock_results = await acquire_locks(redis, unit_ids, str(agent_id))

    all_acquired = all(r.acquired for r in lock_results)
    if not all_acquired:
        branch.status = "open"
        await session.flush()
        raise TimeoutError("LOCK_ACQUISITION_FAILED")

    try:
        # Check each branch unit for conflicts with existing siblings
        conflict_ids: list[str] = []

        for unit in branch_units:
            # Find parent edges
            parent_edges = (
                await session.execute(
                    select(ContextEdge).where(
                        ContextEdge.child_id == unit.id,
                        ContextEdge.relation == EdgeRelation.derived_from,
                    )
                )
            ).scalars().all()

            if not parent_edges:
                continue  # orphan unit, nothing to check

            parent_ids = [e.parent_id for e in parent_edges]

            # Find existing children of the same parents
            existing_children = (
                await session.execute(
                    select(ContextUnit).where(
                        ContextUnit.id.in_(
                            select(ContextEdge.child_id).where(
                                ContextEdge.parent_id.in_(parent_ids),
                                ContextEdge.relation == EdgeRelation.derived_from,
                                ContextEdge.child_id != unit.id,
                            )
                        )
                    )
                )
            ).scalars().all()

            overlapping = False
            for existing in existing_children:
                if detect_overlap(unit.content, existing.content):
                    overlapping = True
                    break

            if overlapping:
                # Create PendingBranch for this conflict
                pending = PendingBranch(
                    context_unit_id=unit.id,
                    branch_id=branch.id,
                    conflict_type="merge_conflict",
                    resolution="pending",
                )
                session.add(pending)
                await session.flush()
                conflict_ids.append(str(pending.id))

        if conflict_ids:
            # Conflicts found — leave branch open
            branch.status = "open"
            await session.commit()
            return MergeResult(
                status="conflict",
                conflict_ids=conflict_ids,
            )

        # No conflicts — auto-merge all branch units
        from loom.services.coordination.merge import auto_merge

        merge_unit_ids: list[str] = []
        for unit in branch_units:
            parent_edges = (
                await session.execute(
                    select(ContextEdge).where(
                        ContextEdge.child_id == unit.id,
                        ContextEdge.relation == EdgeRelation.derived_from,
                    )
                )
            ).scalars().all()
            parent_ids = [e.parent_id for e in parent_edges]

            merge_unit = await auto_merge(
                session,
                branch.project_id,
                agent_id,
                unit.id,
                parent_ids,
            )
            if merge_unit is not None:
                merge_unit_ids.append(str(merge_unit.id))

        # Mark branch as merged
        branch.status = "merged"
        branch.merged_at = datetime.now(timezone.utc)

        # Append merge event
        session.add(
            EventLog(
                project_id=branch.project_id,
                event_type=EventType.merge,
                payload={
                    "branch_id": str(branch.id),
                    "branch_name": branch.name,
                    "merge_unit_ids": merge_unit_ids,
                    "unit_count": len(branch_units),
                },
            )
        )

        await session.commit()
        return MergeResult(
            status="merged",
            merge_unit_id=merge_unit_ids[0] if merge_unit_ids else None,
        )

    except Exception:
        await session.rollback()
        branch.status = "open"
        await session.commit()
        raise
    finally:
        # Release all acquired locks
        for uid in unit_ids:
            await release_lock(redis, uid, str(agent_id))
