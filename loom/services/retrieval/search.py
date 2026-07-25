"""Hybrid search module: vector + keyword search with Reciprocal Rank Fusion.

Phase 2.3 — Combines pgvector ANN cosine similarity with GIN full-text search
via RRF scoring.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models.context_units import ContextUnit
from loom.services.retrieval.providers import EmbeddingProvider, from_config

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────────────────────

_embedding_provider: EmbeddingProvider | None = None


def _get_provider() -> EmbeddingProvider:
    """Get or create the embedding provider singleton."""
    global _embedding_provider  # noqa: PLW0603
    if _embedding_provider is None:
        _embedding_provider = from_config()
    return _embedding_provider


async def encode_query(query: str) -> list[float] | None:
    """Encode a natural-language query into an embedding vector.

    Parameters
    ----------
    query : str
        The user's natural-language query (already stripped, non-empty).

    Returns
    -------
    list[float] | None
        A 1536-dimensional embedding vector, or ``None`` if the query
        is empty / un-embeddable.

    Raises
    ------
    Exception
        Propagates any provider errors (network, API auth, etc.) so the
        caller can decide whether to degrade gracefully.
    """
    provider = _get_provider()
    try:
        return await provider.embed(query)
    except Exception:
        # If the cached provider fails (e.g. stale mock from a prior test),
        # reset the singleton and try once more before propagating.
        global _embedding_provider  # noqa: PLW0603
        _embedding_provider = None
        provider = _get_provider()
        return await provider.embed(query)


# ── Sub-search functions ───────────────────────────────────────────────────────

VECTOR_SEARCH_LIMIT = 50
"""Number of candidates to retrieve from vector ANN search."""

KEYWORD_SEARCH_LIMIT = 50
"""Number of candidates to retrieve from GIN full-text search."""


async def vector_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    query_embedding: list[float],
    *,
    scope_type_filter: str | None = None,
) -> list[dict]:
    """Perform vector ANN search using pgvector cosine similarity.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    query_embedding : list[float]
        Query vector from :func:`encode_query`.
    scope_type_filter : str | None
        If set, filters to units where ``type = :scope_type``
        (e.g. ``"summary"`` for onboarding).

    Returns
    -------
    list[dict]
        Each dict has keys: ``id``, ``type``, ``trust_tier``, ``content``,
        ``created_at``, ``agent_id``, ``vector_score``.

    Notes
    -----
    Uses ``<=>`` (cosine distance) via the pgvector SQLAlchemy comparator
    and converts to similarity via ``1 - distance``.  Only returns units
    with a non-null embedding.
    """
    stmt = select(
        ContextUnit.id,
        ContextUnit.type,
        ContextUnit.trust_tier,
        ContextUnit.content,
        ContextUnit.created_at,
        ContextUnit.agent_id,
        ContextUnit.version,
        (1 - ContextUnit.embedding.cosine_distance(query_embedding)).label(
            "vector_score"
        ),
    ).where(
        ContextUnit.project_id == project_id,
        ContextUnit.embedding.isnot(None),
    )

    if scope_type_filter:
        stmt = stmt.where(ContextUnit.type == scope_type_filter)

    stmt = stmt.order_by(
        ContextUnit.embedding.cosine_distance(query_embedding)
    ).limit(VECTOR_SEARCH_LIMIT)

    rows = (await session.execute(stmt)).mappings().all()

    return [
        {
            "id": str(row["id"]),
            "type": row["type"],
            "trust_tier": row["trust_tier"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat(),
            "agent_id": str(row["agent_id"]),
            "version": int(row["version"]),
            "vector_score": float(row["vector_score"]),
        }
        for row in rows
    ]


async def keyword_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    *,
    scope_type_filter: str | None = None,
) -> list[dict]:
    """Perform GIN full-text keyword search.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    query : str
        Natural-language keyword query.
    scope_type_filter : str | None
        If set, filters to units where ``type = :scope_type``.

    Returns
    -------
    list[dict]
        Each dict has keys: ``id``, ``type``, ``trust_tier``, ``content``,
        ``created_at``, ``agent_id``, ``keyword_score``.
    """
    conditions = [
        "u.project_id = :project_id",
        "to_tsvector('english', u.content) @@ plainto_tsquery('english', :query)",
    ]
    params: dict = {"project_id": project_id, "query": query}

    if scope_type_filter:
        conditions.append("u.type = :scope_type")
        params["scope_type"] = scope_type_filter

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT u.id, u.type, u.trust_tier, u.content, u.created_at, u.agent_id,
               u.version,
               ts_rank(to_tsvector('english', u.content),
                       plainto_tsquery('english', :query)) AS keyword_score
        FROM context_units u
        WHERE {where_clause}
        ORDER BY keyword_score DESC
        LIMIT :limit
    """)

    rows = (
        await session.execute(sql, params | {"limit": KEYWORD_SEARCH_LIMIT})
    ).mappings().all()

    return [
        {
            "id": str(row["id"]),
            "type": row["type"],
            "trust_tier": row["trust_tier"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat(),
            "agent_id": str(row["agent_id"]),
            "version": int(row["version"]),
            "keyword_score": float(row["keyword_score"]),
        }
        for row in rows
    ]


# ── RRF Fusion ──────────────────────────────────────────────────────────────────

RRF_K = 60
"""Constant k for the RRF formula: score = SUM(1 / (k + rank(item)))."""


def rrf_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = RRF_K,
) -> list[dict]:
    """Combine two ranked result lists using Reciprocal Rank Fusion.

    Parameters
    ----------
    vector_results : list[dict]
        Results from :func:`vector_search`, each with an ``id`` key.
    keyword_results : list[dict]
        Results from :func:`keyword_search`, each with an ``id`` key.
    k : int
        RRF constant (default 60).

    Returns
    -------
    list[dict]
        Merged list sorted by ``rrf_score`` descending.  Each dict
        preserves its original keys plus an ``rrf_score`` key.
        Duplicate IDs (present in both lists) appear once with
        scores summed from both lists.
    """
    scores: dict[str, float] = {}
    seen: dict[str, dict] = {}

    # Process vector results preserving first-seen order
    for rank, item in enumerate(vector_results, start=1):
        uid = item["id"]
        scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank)
        if uid not in seen:
            seen[uid] = item

    # Process keyword results
    for rank, item in enumerate(keyword_results, start=1):
        uid = item["id"]
        scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank)
        if uid not in seen:
            seen[uid] = item

    # Build result list with computed scores
    result = []
    for uid, item in seen.items():
        entry = dict(item)
        entry["rrf_score"] = scores[uid]
        result.append(entry)

    # Sort by RRF score descending
    result.sort(key=lambda u: u["rrf_score"], reverse=True)
    return result


def _normalize_rrf_scores(units: list[dict]) -> list[dict]:
    """Normalize RRF scores to [0, 1] by dividing by the max score.

    This ensures the 0.4 weight in :func:`_compute_score` is meaningful
    when ``ts_rank`` is replaced with the normalized RRF value.

    If all scores are 0 (shouldn't happen with non-empty input), the
    units are returned unchanged.
    """
    if not units:
        return units

    max_score = max(u["rrf_score"] for u in units)
    if max_score <= 0:
        return units

    for u in units:
        u["rrf_score"] = round(u["rrf_score"] / max_score, 6)
    return units


def compute_final_scores(units: list[dict]) -> list[dict]:
    """Apply the full ranking formula to RRF-fused results.

    Delegates to :func:`loom.services.context.service._compute_score`
    passing the normalized ``rrf_score`` as the ``ts_rank`` argument.

    Each output dict gains a ``relevance_score`` key (float, 4 decimal places).
    Input dicts must have keys: ``rrf_score``, ``created_at``, ``trust_tier``,
    ``type``.

    Parameters
    ----------
    units : list[dict]
        RRF-fused results with ``rrf_score`` set.

    Returns
    -------
    list[dict]
        Same list with ``relevance_score`` added, sorted descending.
    """
    from loom.services.context.service import _compute_score

    for u in units:
        created_at = (
            datetime.fromisoformat(u["created_at"])
            if isinstance(u["created_at"], str)
            else u["created_at"]
        )
        score = _compute_score(
            ts_rank=u["rrf_score"],  # normalized RRF replaces ts_rank
            created_at=created_at,
            trust_tier=u["trust_tier"],
            unit_type=u.get("type", ""),
        )
        u["relevance_score"] = round(score, 4)

    units.sort(key=lambda u: u["relevance_score"], reverse=True)
    return units


# ── Token budget packing ───────────────────────────────────────────────────────

_CHARS_PER_TOKEN = 8


def _token_count(text_content: str) -> int:
    """Approximate token count (4 chars ~= 1 token)."""
    return max(1, math.ceil(len(text_content) / _CHARS_PER_TOKEN))


def pack_results(
    units: list[dict],
    budget: int,
) -> dict:
    """Pack ranked units into the token budget.

    Parameters
    ----------
    units : list[dict]
        Ranked results from :func:`compute_final_scores`, each with
        ``content``, ``id``, and ``relevance_score`` keys.
    budget : int
        Max tokens to return (already clamped by the caller).

    Returns
    -------
    dict
        ``{"units": [...], "total_tokens": int, "truncated": bool}``
        where ``total_tokens`` is the number of tokens consumed by
        the packed units (≤ budget).
    """
    packed: list[dict] = []
    budget_used = 0
    truncated = False

    for unit in units:
        tokens = _token_count(unit["content"])

        if budget_used + tokens <= budget:
            packed.append(unit)
            budget_used += tokens
        elif budget_used < budget:
            remaining = budget - budget_used
            max_chars = remaining * _CHARS_PER_TOKEN
            unit["content"] = unit["content"][:max_chars]
            unit["truncated"] = True
            truncated = True
            packed.append(unit)
            budget_used = budget
            break
        else:
            break

    return {
        "units": packed,
        "total_tokens": budget_used,
        "truncated": truncated,
    }


# ── Hybrid search orchestrator ──────────────────────────────────────────────────


async def hybrid_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    *,
    scope_type_filter: str | None = None,
    budget: int,
) -> dict:
    """Run a hybrid vector+keyword search with Reciprocal Rank Fusion.

    This is the main entry point for hybrid retrieval.  Callers should
    use this in preference to calling :func:`vector_search` or
    :func:`keyword_search` directly.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    query : str
        Non-empty natural-language query (caller ensures it is stripped
        and non-empty before calling this function).
    scope_type_filter : str | None
        Optional type filter for scope-based retrieval.
    budget : int
        Max tokens to return (caller clamps before passing).

    Returns
    -------
    dict
        ``{"units": [...], "total_tokens": int, "truncated": bool, "degraded": bool}``

        ``degraded`` is ``True`` when the query embedding step failed
        and the result is keyword-only.

    Raises
    ------
    ValueError
        If ``query`` is empty or ``None`` — the caller's responsibility
        to validate before calling.

    Notes
    -----
    **Graceful degradation:**
    If ``encode_query`` raises an exception (network error, API auth failure),
    this function logs a warning and falls back to keyword-only search with
    ``degraded: true``.  It does NOT re-raise — the read path always returns
    results, even if unranked.

    **Empty results:**
    If both sub-queries return no results, returns a zero-result dict
    matching the return type.
    """
    if not query or not query.strip():
        raise ValueError("query must be non-empty for hybrid_search")

    # ── Step 1: Encode query ──────────────────────────────────────────
    degraded = False
    query_embedding: list[float] | None = None

    try:
        query_embedding = await encode_query(query)
    except Exception:
        logger.warning("Query encoding failed — falling back to keyword-only")
        degraded = True

    # ── Step 2: Execute sub-queries ───────────────────────────────────
    if query_embedding is not None:
        # Full hybrid path
        vector_task = vector_search(
            session,
            project_id,
            query_embedding,
            scope_type_filter=scope_type_filter,
        )
        keyword_task = keyword_search(
            session,
            project_id,
            query,
            scope_type_filter=scope_type_filter,
        )
        # Run sequentially — asyncpg sessions are not concurrency-safe
        vector_results = await vector_task
        keyword_results = await keyword_task

        # ── Step 3: RRF fusion ───────────────────────────────────────
        fused = rrf_fusion(vector_results, keyword_results)
        fused = _normalize_rrf_scores(fused)

    else:
        # Degraded path: keyword-only (or empty results if no query)
        keyword_results = await keyword_search(
            session,
            project_id,
            query,
            scope_type_filter=scope_type_filter,
        )
        # On degraded path, use keyword_score as the score directly
        fused = keyword_results
        for u in fused:
            u["rrf_score"] = u.get("keyword_score", 0.0)
        fused = _normalize_rrf_scores(fused)

    if not fused:
        return {"units": [], "total_tokens": 0, "truncated": False, "degraded": degraded}

    # ── Step 4: Compute final scores ─────────────────────────────────
    scored = compute_final_scores(fused)

    # ── Step 5: Pack into budget ─────────────────────────────────────
    packed = pack_results(scored, budget)
    packed["degraded"] = degraded
    return packed
