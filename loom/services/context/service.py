"""Context Service — write path.

Transactional write of a ContextUnit with idempotency, version-conflict
detection, edge creation, and event-log append.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import (
    Agent,
    ContextEdge,
    ContextUnit,
    ContextUnitType,
    EdgeRelation,
    EventLog,
    EventType,
    Project,
    TrustTier,
)


async def write_context(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    client_uuid: uuid.UUID,
    type_: str,
    content: str,
    version: int,
    trust_tier: str | None = None,
    parent_ids: list[str] | None = None,
    parent_relations: list[str] | None = None,
) -> tuple[ContextUnit, bool]:
    """Write a new context unit in a single transaction.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy async session.
    project_id : uuid.UUID
        Target project.
    agent_id : uuid.UUID
        Authenticated agent writing the unit.
    client_uuid : uuid.UUID
        Client-supplied idempotency key (unique across the project).
    type_ : str
        One of ContextUnitType enum values.
    content : str
        Non-empty text content.
    version : int
        Version number in the parent lineage.
    trust_tier : str | None
        One of TrustTier enum values (defaults to ``"agent"``).
    parent_ids : list[str] | None
        UUIDs of parent context units this unit derives from.
    parent_relations : list[str] | None
        Edge relations for each parent (defaults to ``"derived_from"``).

    Returns
    -------
    tuple[ContextUnit, bool]
        The created (or pre-existing) unit and a boolean ``is_new`` flag
        indicating whether the unit was freshly created in this transaction.

    Raises
    ------
    ValueError
        With one of the following error codes:
        - ``PROJECT_NOT_FOUND`` → 404
        - ``AGENT_MISMATCH`` → 403
        - ``INVALID_TYPE`` → 400
        - ``EMPTY_CONTENT`` → 400
        - ``CONFLICT`` → 409
        - ``PARENT_NOT_FOUND`` → 404
    """
    # ── 1. Validate project ──────────────────────────────────────────────
    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError("PROJECT_NOT_FOUND")

    # ── 2. Validate agent belongs to project ─────────────────────────────
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise ValueError("AGENT_MISMATCH")

    # ── 3. Validate type enum ────────────────────────────────────────────
    try:
        unit_type = ContextUnitType(type_)
    except ValueError:
        raise ValueError("INVALID_TYPE")

    # ── 4. Validate non-empty content ────────────────────────────────────
    if not content.strip():
        raise ValueError("EMPTY_CONTENT")

    # ── 5. Idempotency check (client_uuid unique) ────────────────────────
    existing: ContextUnit | None = (
        await session.execute(
            select(ContextUnit).where(ContextUnit.client_uuid == client_uuid)
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing, False  # idempotent replay — not newly created

    # ── 6. Version-conflict check ────────────────────────────────────────
    parent_uuids: list[uuid.UUID] = []
    parent_ids_list = parent_ids or []
    parent_relations_list = parent_relations or []

    if parent_ids_list:
        parent_versions: list[int] = []
        for pid_str in parent_ids_list:
            try:
                pid = uuid.UUID(pid_str)
            except ValueError:
                raise ValueError("PARENT_NOT_FOUND")
            parent_uuids.append(pid)

            parent = await session.get(ContextUnit, pid)
            if parent is None:
                raise ValueError("PARENT_NOT_FOUND")
            parent_versions.append(parent.version)

        max_parent_version = max(parent_versions)
        expected_version = max_parent_version + 1
        if version != expected_version:
            raise ValueError("CONFLICT")

    # ── 7. Determine trust_tier ──────────────────────────────────────────
    if trust_tier:
        try:
            tier = TrustTier(trust_tier)
        except ValueError:
            tier = TrustTier.agent
    else:
        tier = TrustTier.agent

    # ── 8. Create ContextUnit ────────────────────────────────────────────
    unit = ContextUnit(
        project_id=project_id,
        agent_id=agent_id,
        client_uuid=client_uuid,
        type=unit_type,
        trust_tier=tier,
        content=content,
        version=version,
    )
    session.add(unit)
    await session.flush()  # materialise the PK so we can use it in edges

    # ── 9. Create parent edges ────────────────────────────────────────────
    for i, pid in enumerate(parent_uuids):
        relation = EdgeRelation.derived_from
        if i < len(parent_relations_list):
            try:
                relation = EdgeRelation(parent_relations_list[i])
            except ValueError:
                pass  # fall back to derived_from for unknown relations

        edge = ContextEdge(
            parent_id=pid,
            child_id=unit.id,
            relation=relation,
        )
        session.add(edge)

    # ── 10. Append event-log entry ────────────────────────────────────────
    event = EventLog(
        project_id=project_id,
        event_type=EventType.write,
        payload={
            "context_unit_id": str(unit.id),
            "client_uuid": str(client_uuid),
            "agent_id": str(agent_id),
            "version": version,
            "type": type_,
        },
    )
    session.add(event)

    await session.commit()
    await session.refresh(unit)
    return unit, True  # freshly created
