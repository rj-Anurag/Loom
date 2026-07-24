"""Context Service.

Write path: transactional write with idempotency, version-conflict detection,
edge creation, and event-log append.

Read path: keyword-based retrieval with PostgreSQL full-text search, ranking,
and token-budget-aware packing (v1 — no embeddings yet).
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, text
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


# ── Read Path ──────────────────────────────────────────────────────────────────


TRUST_TIER_WEIGHTS: dict[str, float] = {
    "user": 1.0,
    "agent": 0.7,
    "external_tool": 0.4,
}

SCOPE_FILTERS: dict[str, str | None] = {
    "onboarding": "summary",
    "task": None,  # all types
    "full": None,  # all types
}

MAX_BUDGET = 32000
DEFAULT_BUDGET = 4096
CHARS_PER_TOKEN = 4


def _token_count(text_content: str) -> int:
    """Approximate token count (4 chars ~= 1 token)."""
    return max(1, math.ceil(len(text_content) / CHARS_PER_TOKEN))


def _compute_score(
    ts_rank: float | None,
    created_at: datetime,
    trust_tier: str,
) -> float:
    """Ranking formula from the plan.

    score = 0.4 * ts_rank
          + 0.3 * (1.0 / (hours_since_creation + 1))
          + 0.3 * trust_tier_weight
    """
    hours_since = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
    recency = 1.0 / (hours_since + 1.0)
    weight = TRUST_TIER_WEIGHTS.get(trust_tier, 0.4)

    return 0.4 * (ts_rank or 0.0) + 0.3 * recency + 0.3 * weight


async def read_context(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    query: str | None = None,
    budget: int = DEFAULT_BUDGET,
    scope: str = "task",
) -> dict:
    """Retrieve context units with keyword filtering and token-budget packing.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy async session.
    project_id : uuid.UUID
        Target project.
    agent_id : uuid.UUID
        Authenticated agent.
    query : str | None
        Natural-language keyword query.  ``None`` or empty returns recent units.
    budget : int
        Max tokens to return (default 4096, max 32000).
    scope : str
        One of ``"onboarding"``, ``"task"`` (default), or ``"full"``.

    Returns
    -------
    dict
        ``{"units": [...], "total_tokens": int, "budget_used": int, "truncated": bool}``
    """
    # ── Validate project ────────────────────────────────────────────────
    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError("PROJECT_NOT_FOUND")

    # ── Validate agent belongs to project ───────────────────────────────
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise ValueError("AGENT_MISMATCH")

    # ── Clamp budget ────────────────────────────────────────────────────
    budget = min(max(budget, 1), MAX_BUDGET)
    query = query.strip() if query else None

    # ── Build the search query ──────────────────────────────────────────
    scope_type_filter = SCOPE_FILTERS.get(scope)
    conditions = ["u.project_id = :project_id"]
    params: dict = {"project_id": project_id, "query": query or ""}

    if query:
        conditions.append(
            "to_tsvector('english', u.content) @@ plainto_tsquery('english', :query)"
        )

    if scope_type_filter:
        conditions.append("u.type = :scope_type")
        params["scope_type"] = scope_type_filter

    where_clause = " AND ".join(conditions)

    search_sql = text(f"""
        SELECT
            u.id,
            u.type,
            u.trust_tier,
            u.content,
            u.created_at,
            u.agent_id,
            ts_rank(to_tsvector('english', u.content),
                    plainto_tsquery('english', COALESCE(:query, ''))) AS rank
        FROM context_units u
        WHERE {where_clause}
        ORDER BY
            {_compute_score_sql()} DESC
        LIMIT 200
    """)

    rows = (await session.execute(search_sql, params)).mappings().all()

    if not rows:
        return {"units": [], "total_tokens": 0, "budget_used": 0, "truncated": False}

    # ── Compute scores ──────────────────────────────────────────────────
    scored: list[dict] = []
    for row in rows:
        score = _compute_score(
            ts_rank=row["rank"],
            created_at=row["created_at"],
            trust_tier=row["trust_tier"],
        )
        scored.append({
            "id": str(row["id"]),
            "type": row["type"],
            "trust_tier": row["trust_tier"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat(),
            "agent_id": str(row["agent_id"]),
            "relevance_score": round(score, 4),
        })

    # Sort by score descending (already ordered by SQL, but be safe)
    scored.sort(key=lambda u: u["relevance_score"], reverse=True)

    # ── Batch-load parent edges ─────────────────────────────────────────
    unit_ids = [uuid.UUID(u["id"]) for u in scored]
    edge_rows = await session.execute(
        select(ContextEdge.parent_id, ContextEdge.child_id).where(
            ContextEdge.child_id.in_(unit_ids)
        )
    )
    parent_map: dict[str, list[str]] = defaultdict(list)
    for edge in edge_rows:
        parent_map[str(edge.child_id)].append(str(edge.parent_id))

    # ── Pack into token budget ──────────────────────────────────────────
    packed_units: list[dict] = []
    budget_used = 0
    truncated = False

    for unit in scored:
        tokens = _token_count(unit["content"])
        unit["parent_ids"] = parent_map.get(unit["id"], [])

        if budget_used + tokens <= budget:
            # Fits entirely
            packed_units.append(unit)
            budget_used += tokens
        elif budget_used < budget:
            # Partially fits — truncate
            remaining = budget - budget_used
            max_chars = remaining * CHARS_PER_TOKEN
            unit["content"] = unit["content"][:max_chars]
            truncated = True
            packed_units.append(unit)
            budget_used = budget
            break
        else:
            break

    return {
        "units": packed_units,
        "total_tokens": budget_used,
        "budget_used": budget_used,
        "truncated": truncated,
    }


def _compute_score_sql() -> str:
    """Return the SQL expression for the ranking formula."""
    return (
        "(0.4 * COALESCE(ts_rank(to_tsvector('english', u.content), "
        "plainto_tsquery('english', COALESCE(:query, ''))), 0)"
        " + 0.3 * (1.0 / (EXTRACT(EPOCH FROM (now() - u.created_at)) / 3600.0 + 1.0))"
        " + 0.3 * CASE u.trust_tier"
        "     WHEN 'user' THEN 1.0"
        "     WHEN 'agent' THEN 0.7"
        "     ELSE 0.4"
        "   END)"
    )
