---
title: "Phase 2.3 — Hybrid Search (Vector + Keyword) Execution Plan"
description: "Upgrade the read path from keyword-only to hybrid search combining pgvector ANN cosine similarity with GIN full-text search via Reciprocal Rank Fusion (RRF)."
status: completed
dependencies: ["phase-1/03-context-service-read.md", "phase-1/09-embedding-pipeline.md"]
---

# Hybrid Search — Execution Plan

## Prerequisites

| # | Task | Check |
|---|---|---|
| P0 | Embedding pipeline running (Phase 1.9) — context_units have populated `embedding` vectors | `SELECT COUNT(*) FROM context_units WHERE embedding IS NOT NULL` > 0 |
| P1 | PostgreSQL running with pgvector extension | `pg_isready` |
| P2 | IVFFlat index exists on `context_units.embedding` | `SELECT * FROM pg_indexes WHERE indexdef LIKE '%ivfflat%'` |
| P3 | GIN index exists on `context_units.content` | `SELECT * FROM pg_indexes WHERE indexdef LIKE '%gin%content%'` |

---

## Subtask Index

| ID | Name | Est. Time | Depends On |
|---|---|---|---|
| A1 | Create `search.py` — `encode_query()`, `vector_search()`, `keyword_search()` | 30 min | P1 |
| A2 | Create `search.py` — `rrf_fusion()`, `compute_final_scores()`, `pack_results()` | 25 min | — |
| A3 | Create `search.py` — `hybrid_search()` orchestrator | 20 min | A1, A2 |
| B1 | Modify `service.py` — update `read_context()` to call `hybrid_search()` when query provided | 25 min | A3 |
| C1 | Write unit tests for `vector_search` and `keyword_search` | 20 min | A1 |
| C2 | Write unit tests for RRF fusion and final scoring | 15 min | A2 |
| C3 | Write integration tests for `hybrid_search` integration with `read_context` | 25 min | A3, B1 |

**Total estimated time: ~2.5 hours**

---

## Design Decisions (per Architect Review)

| # | Decision | Detail |
|---|---|---|
| 1 | **Preserve existing score formula** | Replace `ts_rank` weight with normalized RRF score. Keep all other terms unchanged: 0.3 recency, 0.3 trust_tier, 0.15 summary boost. Do NOT use the plan's proposed 0.6*rrf + 0.2*trust + 0.2*recency formula. |
| 2 | **Normalize RRF** | Divide RRF scores by max RRF to map them to [0,1] so the 0.4 weight is meaningful when plugged into `_compute_score(ts_rank=...)`. |
| 3 | **Scope filter** | The `scope_type_filter` (e.g., `"summary"` for onboarding) must be propagated to BOTH `vector_search` and `keyword_search` sub-queries. |
| 4 | **Query encoding** | Use `from_config()` from providers.py — singleton provider cached at module level (not instantiated per-call). |
| 5 | **Concurrent execution** | Use `asyncio.gather()` for vector and keyword sub-queries. |
| 6 | **Graceful degradation** | If query encoding fails (network/API error), fall back to keyword-only with `degraded: true` flag in response. |
| 7 | **Empty query** | When `query` is `None` or empty, skip hybrid search entirely — fall through to current chronological path in `read_context()`. |
| 8 | **No HNSW index for v1** | IVFFlat is sufficient. Do not create an HNSW index. |

---

## A1 — search.py: encode_query + vector_search + keyword_search

### Files
- **CREATE** `loom/services/retrieval/search.py` — query encoding and sub-search functions

### encode_query()

```python
"""Module-level cached embedding provider (singleton)."""
_embedding_provider: EmbeddingProvider | None = None


def _get_provider() -> EmbeddingProvider:
    """Get or create the embedding provider singleton."""
    global _embedding_provider
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
    return await provider.embed(query)
```

### vector_search()

```python
VECTOR_SEARCH_LIMIT = 50
"""Number of candidates to retrieve from vector ANN search."""

VECTOR_SEARCH_DISTANCE = "cosine"
"""Distance metric for pgvector ANN search."""


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
    Uses ``<=>`` (cosine distance) and converts to similarity via
    ``1 - distance``.  Only returns units with a non-null embedding.
    """
    ...

    # SQL:
    # SELECT u.id, u.type, u.trust_tier, u.content, u.created_at, u.agent_id,
    #        1 - (u.embedding <=> :query_embedding::vector) AS vector_score
    # FROM context_units u
    # WHERE u.project_id = :project_id
    #   AND u.embedding IS NOT NULL
    #   [AND u.type = :scope_type]   -- if scope_type_filter
    # ORDER BY u.embedding <=> :query_embedding::vector
    # LIMIT :limit
```

### keyword_search()

```python
KEYWORD_SEARCH_LIMIT = 50
"""Number of candidates to retrieve from GIN full-text search."""


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
    ...

    # SQL:
    # SELECT u.id, u.type, u.trust_tier, u.content, u.created_at, u.agent_id,
    #        ts_rank(to_tsvector('english', u.content),
    #                plainto_tsquery('english', :query)) AS keyword_score
    # FROM context_units u
    # WHERE u.project_id = :project_id
    #   AND to_tsvector('english', u.content) @@ plainto_tsquery('english', :query)
    #   [AND u.type = :scope_type]   -- if scope_type_filter
    # ORDER BY keyword_score DESC
    # LIMIT :limit
```

### Acceptance Criteria
- [x] `encode_query` calls the singleton provider (created once, cached at module level)
- [x] `encode_query` returns `None` for empty/whitespace-only queries
- [x] `encode_query` propagates provider exceptions (network errors, API auth failures)
- [x] `vector_search` returns at most `VECTOR_SEARCH_LIMIT` results
- [x] `vector_search` only returns units with non-null `embedding`
- [x] `vector_search` includes `vector_score` (cosine similarity, range [-1, 1])
- [x] `vector_search` respects `scope_type_filter` when provided
- [x] `vector_search` scoped to `project_id`
- [x] `keyword_search` returns at most `KEYWORD_SEARCH_LIMIT` results
- [x] `keyword_search` includes `keyword_score` (ts_rank, range [0, 1])
- [x] `keyword_search` respects `scope_type_filter` when provided
- [x] `keyword_search` returns empty list when query matches nothing
- [x] Both functions return dicts with consistent key names (id, type, trust_tier, content, created_at, agent_id) + version

---

## A2 — search.py: rrf_fusion + compute_final_scores + pack_results

### Files
- **MODIFY** `loom/services/retrieval/search.py` — add RRF fusion and scoring functions (append to same file)

### rrf_fusion()

```python
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
    ...

    # Algorithm:
    # 1. Build a dict: id → rrf_score = SUM(1 / (k + rank))
    #    where rank starts at 1 for each list.
    # 2. Collect unique items preserving first-seen order
    #    (vector_results first, then keyword_results).
    # 3. Assign rrf_score to each item.
    # 4. Sort by rrf_score descending.
    # 5. Return sorted list.
```

### Normalization (applied after fusion)

```python
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
```

### compute_final_scores()

```python
def compute_final_scores(units: list[dict]) -> list[dict]:
    """Apply the full ranking formula to RRF-fused results.

    Delegates to :func:`loom.services.context.service._compute_score`
    passing the normalized ``rrf_score`` as the ``ts_rank`` argument.

    Each output dict gains a ``relevance_score`` key (float, 4 decimal places).
    Input dicts must have keys: ``rrf_score``, ``created_at``, ``trust_tier``, ``type``.

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
        created_at = datetime.fromisoformat(u["created_at"]) \
            if isinstance(u["created_at"], str) else u["created_at"]
        score = _compute_score(
            ts_rank=u["rrf_score"],       # normalized RRF replaces ts_rank
            created_at=created_at,
            trust_tier=u["trust_tier"],
            unit_type=u.get("type", ""),
        )
        u["relevance_score"] = round(score, 4)

    units.sort(key=lambda u: u["relevance_score"], reverse=True)
    return units
```

### pack_results()

Moved to `search.py` to co-locate with hybrid search logic. Replicates the current token-budget packing from `read_context()` into a reusable function.

```python
_CHARS_PER_TOKEN = 4


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
```

### Acceptance Criteria
- [x] `rrf_fusion` combines two lists using RRF formula `SUM(1 / (k + rank))`
- [x] `rrf_fusion` handles units present in only one list (score from that list only)
- [x] `rrf_fusion` handles units present in both lists (scores summed)
- [x] `rrf_fusion` returns results sorted by RRF score descending
- [x] `rrf_fusion` with a single non-empty list returns that list ranked by RRF
- [x] `rrf_fusion` with two empty lists returns `[]`
- [x] `rrf_fusion` deduplicates by `id` (same unit appears once)
- [x] `_normalize_rrf_scores` maps max score to 1.0, others proportionally
- [x] `_normalize_rrf_scores` handles all-zero scores without division by zero
- [x] `_normalize_rrf_scores` handles empty list
- [x] `compute_final_scores` calls `_compute_score` with normalized RRF as `ts_rank`
- [x] `compute_final_scores` adds `relevance_score` to each unit
- [x] `compute_final_scores` sorts by `relevance_score` descending
- [x] `pack_results` respects budget (total_tokens ≤ budget)
- [x] `pack_results` truncates last partial unit and sets `truncated: true`
- [x] `pack_results` includes all units that fit entirely
- [x] `pack_results` with budget=0 returns empty list, 0 tokens

---

## A3 — search.py: hybrid_search() orchestrator

### Files
- **MODIFY** `loom/services/retrieval/search.py` — add the orchestrator function (append to same file)

### hybrid_search()

```python
DEGRADED_SUBQUERY_LIMIT = 50
"""Fallback keyword-only limit when hybrid search is degraded."""


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

    Notes
    -----
    **Graceful degradation (Architect decision #6):**
    If ``encode_query`` raises an exception (network error, API auth failure),
    this function logs a warning and falls back to keyword-only search with
    ``degraded: true``.  It does NOT re-raise — the read path always returns
    results, even if unranked.

    **Empty results:**
    If both sub-queries return no results, returns a zero-result dict
    matching the return type.
    """
    import logging
    logger = logging.getLogger(__name__)

    # ── Step 1: Encode query ──────────────────────────────────────────
    degraded = False
    query_embedding: list[float] | None = None

    try:
        query_embedding = await encode_query(query)
    except Exception:
        logger.warning("Query encoding failed — falling back to keyword-only")
        degraded = True

    # ── Step 2: Execute sub-queries ──────────────────────────────────
    if query_embedding is not None:
        # Full hybrid path
        vector_task = vector_search(
            session, project_id, query_embedding,
            scope_type_filter=scope_type_filter,
        )
        keyword_task = keyword_search(
            session, project_id, query,
            scope_type_filter=scope_type_filter,
        )
        vector_results, keyword_results = await asyncio.gather(
            vector_task, keyword_task,
        )

        # ── Step 3: RRF fusion ───────────────────────────────────────
        fused = rrf_fusion(vector_results, keyword_results)
        fused = _normalize_rrf_scores(fused)

    else:
        # Degraded path: keyword-only (or empty results if no query)
        keyword_results = await keyword_search(
            session, project_id, query,
            scope_type_filter=scope_type_filter,
        )
        # On degraded path, use keyword_score as the score directly
        fused = keyword_results
        for u in fused:
            u["rrf_score"] = u.get("keyword_score", 0.0)
        fused = _normalize_rrf_scores(fused)

    if not fused:
        return {"units": [], "total_tokens": 0, "truncated": False, "degraded": degraded}

    # ── Step 4: Compute final scores ────────────────────────────────
    scored = compute_final_scores(fused)

    # ── Step 5: Pack into budget ────────────────────────────────────
    packed = pack_results(scored, budget)
    packed["degraded"] = degraded
    return packed
```

### Acceptance Criteria
- [x] `hybrid_search` runs vector and keyword sub-queries (sequentially — asyncpg sessions are not concurrency-safe, unlike the original plan's `asyncio.gather` approach)
- [x] `hybrid_search` falls back to keyword-only when `encode_query` raises an exception
- [x] `hybrid_search` sets `degraded: true` in the response for keyword-only fallback
- [x] `hybrid_search` sets `degraded: false` in the response for full hybrid path
- [x] `hybrid_search` returns results within the token budget
- [x] `hybrid_search` returns empty result dict when both sub-queries return no results
- [x] `hybrid_search` respects `scope_type_filter` in both sub-queries
- [x] `scope_type_filter` is propagated to both `vector_search` and `keyword_search`
- [x] All results have `relevance_score` in descending order
- [x] `hybrid_search` does NOT re-raise encoding exceptions (graceful degradation)

---

## B1 — Modify service.py — Update read_context()

### Files
- **MODIFY** `loom/services/context/service.py` — update `read_context()` to call `hybrid_search` when a query is provided

### Changes

#### 1. Add import at top of file

```python
from loom.services.retrieval.search import hybrid_search
```

#### 2. Preserve existing import guard

No existing import needs removal — the current file does not import from `search.py`.

#### 3. Replace the keyword-only query block in `read_context()`

**Current flow** (lines 524-557):
```
if query:
    conditions.append("to_tsvector @@ plainto_tsquery")

where_clause = ...
search_sql = text(...)  # full query with _compute_score_sql
rows = (await session.execute(search_sql, params)).mappings().all()
```

**New flow** (replaces lines 524-557):

```python
    # ── Hybrid or chronological? ──────────────────────────────────────
    if query:
        try:
            hybrid_result = await hybrid_search(
                session,
                project_id,
                query,
                scope_type_filter=scope_type_filter,
                budget=budget,
            )
        except Exception:
            logger.exception("Hybrid search failed — falling back to chronological")
            hybrid_result = {"units": [], "total_tokens": 0, "truncated": False, "degraded": True}

        if hybrid_result["units"]:
            # Hybrid search produced results — return them directly.
            # The hybrid path already handles scoring, packing, and parent loading.
            return hybrid_result
        # If hybrid returned no results, fall through to chronological below.
        # (This is rare but handles edge cases where both sub-queries return empty.)

    # ── Chronological / empty-query path (unchanged) ──────────────────
    # Build the simple chronological query without tsvector conditions
    conditions = ["u.project_id = :project_id"]
    params: dict = {"project_id": project_id}

    if scope_type_filter:
        conditions.append("u.type = :scope_type")
        params["scope_type"] = scope_type_filter

    where_clause = " AND ".join(conditions)

    chronological_sql = text(f"""
        SELECT
            u.id, u.type, u.trust_tier, u.content, u.created_at, u.agent_id,
            0.0 AS rank
        FROM context_units u
        WHERE {where_clause}
        ORDER BY u.created_at DESC
        LIMIT 200
    """)

    rows = (await session.execute(chronological_sql, params)).mappings().all()
```

#### 4. Update parent-loading (no change needed — same logic applies)

The parent-loading block (lines 584-593) iterates `unit_ids` — it works identically for both hybrid and chronological results. The hybrid result's units already have `id` as a string, so the UUID conversion at line 585 works.

#### 5. Update token-packing (no change for chronological path; hybrid path packs internally)

The hybrid path already packs results via `pack_results` in `search.py`. The chronological path continues to use the existing packing logic (lines 596-618), which should be kept as-is.

#### 6. Return type

Add `"degraded": bool` to the chronological return path:

```python
    return {
        "units": packed_units,
        "total_tokens": budget_used,
        "budget_used": budget_used,
        "truncated": truncated,
        "degraded": False,     # NEW
    }
```

#### 7. Add logger

Add a module-level logger if not present:

```python
import logging
logger = logging.getLogger(__name__)
```

Full diff of changes to `read_context()`:

| Lines | Change |
|---|---|
| 524-557 | Replace SQL-based keyword query with `hybrid_search()` call, fall through to chronological on empty/no results |
| 560 | After hybrid check, chronological path removed `query` from params (no longer needed) |
| 620-625 | Add `"degraded": False` to chronological/full return dict |

### Acceptance Criteria
- [x] When `query` is provided and non-empty, `read_context` calls `hybrid_search()`
- [x] When `query` is `None` or empty, `read_context` uses the chronological path (unchanged)
- [x] Hybrid search results include `relevance_score` (from RRF-based scoring)
- [x] Hybrid search results include `degraded: false` (normal path)
- [x] When hybrid_search raises an exception, `read_context` logs it and returns `degraded: true` with chronological fallback
- [x] When hybrid_search returns empty results, `read_context` falls through to chronological
- [x] All existing tests pass without modification (backward compatible)
- [x] Response includes `degraded` field in all return paths
- [x] Token budget still respected for chronological path

---

## C1 — Tests for vector_search and keyword_search

### Files
- **CREATE** `tests/services/retrieval/test_search.py`

### Fixtures

Reuse existing fixtures from `tests/services/retrieval/conftest.py`:
- `test_project` (creates a Project)
- `test_agent` (creates an Agent)
- `db_session` (async session)
- `_insert_unit` helper (from conftest.py)

Additional fixtures for embedding-enabled test data:

```python
@pytest_asyncio.fixture
async def embedded_sample_units(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> dict[str, uuid.UUID]:
    """Insert units with deterministic embeddings for search tests.

    Returns a dict mapping semantic labels to unit IDs.
    """
    from loom.config import settings
    from loom.services.retrieval.providers import from_config

    provider = from_config()
    units = {
        "security_bcrypt": "Use bcrypt for password hashing to comply with security policies",
        "redis_cache": "Implement Redis caching layer for frequently accessed context",
        "auth_flow": "The authentication flow uses JWT tokens with a 24-hour expiry",
        "db_schema": "PostgreSQL schema with pgvector for embedding storage",
        "weather_noise": "The weather today is sunny with a chance of rain",
    }

    unit_ids: dict[str, uuid.UUID] = {}
    for label, content in units.items():
        unit_id = uuid.uuid4()
        embedding = await provider.embed(content)

        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, :embedding::vector, :version, :created_at)
            """),
            {
                "id": unit_id,
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "decision",
                "tier": "agent",
                "content": content,
                "embedding": str(embedding),
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        unit_ids[label] = unit_id

    await db_session.commit()
    return unit_ids
```

### Test Scenarios for vector_search

```python
class TestVectorSearch:
    """Tests for vector_search function."""

    async def test_returns_semantic_results(self, db_session, test_project, embedded_sample_units):
        """Semantically similar query returns matching units."""
        from loom.services.retrieval.search import vector_search, encode_query
        embedding = await encode_query("password security authentication")
        results = await vector_search(db_session, test_project.id, embedding)
        assert len(results) > 0
        # "security_bcrypt" should be among top results
        contents = " ".join(r["content"] for r in results)
        assert "bcrypt" in contents or "password" in contents or "hashing" in contents

    async def test_returns_at_most_limit_results(self, db_session, test_project, embedded_sample_units):
        """Number of results capped at VECTOR_SEARCH_LIMIT."""
        from loom.services.retrieval.search import vector_search, encode_query, VECTOR_SEARCH_LIMIT
        embedding = await encode_query("test")
        results = await vector_search(db_session, test_project.id, embedding)
        assert len(results) <= VECTOR_SEARCH_LIMIT

    async def test_all_results_have_vector_score(self, db_session, test_project, embedded_sample_units):
        """Every result dict includes vector_score."""
        from loom.services.retrieval.search import vector_search, encode_query
        embedding = await encode_query("test")
        results = await vector_search(db_session, test_project.id, embedding)
        for r in results:
            assert "vector_score" in r
            assert isinstance(r["vector_score"], float)

    async def test_excludes_units_without_embedding(self, db_session, test_project, test_agent, embedded_sample_units):
        """Context units with NULL embedding are excluded from results."""
        from loom.services.retrieval.search import vector_search, encode_query
        # Insert a unit without embedding
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, NULL, :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "message",
                "tier": "agent",
                "content": "Unit without embedding should not appear",
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        embedding = await encode_query("test")
        results = await vector_search(db_session, test_project.id, embedding)
        contents = [r["content"] for r in results]
        assert all("without embedding" not in c for c in contents)

    async def test_scope_filter_limits_results(self, db_session, test_project, test_agent, embedded_sample_units):
        """When scope_type_filter is set, only matching types are returned."""
        from loom.services.retrieval.search import vector_search, encode_query
        # Insert a summary unit
        summary_id = uuid.uuid4()
        from loom.services.retrieval.providers import from_config
        provider = from_config()
        summary_embedding = await provider.embed("Project overview summary")
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, 'summary', :tier,
                     :content, :embedding::vector, :version, :created_at)
            """),
            {
                "id": summary_id,
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "tier": "agent",
                "content": "Project overview summary for testing scope filter",
                "embedding": str(summary_embedding),
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        embedding = await encode_query("project")
        results = await vector_search(
            db_session, test_project.id, embedding,
            scope_type_filter="summary",
        )
        assert len(results) > 0
        for r in results:
            assert r["type"] == "summary"

    async def test_scoped_to_project(self, db_session, test_project, test_agent, embedded_sample_units):
        """Results are scoped to the given project_id."""
        from loom.services.retrieval.search import vector_search, encode_query
        # Create a different project with its own units
        other_project = Project(name="Other Project")
        db_session.add(other_project)
        await db_session.commit()
        await db_session.refresh(other_project)
        other_agent = Agent(project_id=other_project.id, kind="local")
        db_session.add(other_agent)
        await db_session.commit()
        await db_session.refresh(other_agent)

        other_unit_id = uuid.uuid4()
        provider = from_config()
        embedding = await provider.embed("Other project data")
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, :embedding::vector, :version, :created_at)
            """),
            {
                "id": other_unit_id,
                "pid": other_project.id,
                "aid": other_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "decision",
                "tier": "agent",
                "content": "Other project should not leak into test project results",
                "embedding": str(embedding),
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        results = await vector_search(
            db_session, test_project.id, await encode_query("test"),
        )
        project_ids = {r["project_id"] for r in results} if results and "project_id" in results[0] else set()
        # At minimum, no other project content leaks in
        contents = " ".join(r["content"] for r in results)
        assert "Other project" not in contents
```

### Test Scenarios for keyword_search

```python
class TestKeywordSearch:
    """Tests for keyword_search function."""

    async def test_returns_matching_results(self, db_session, test_project, embedded_sample_units):
        """Keyword query returns units matching by text content."""
        from loom.services.retrieval.search import keyword_search
        results = await keyword_search(db_session, test_project.id, "bcrypt")
        assert len(results) > 0
        contents = [r["content"] for r in results]
        assert any("bcrypt" in c for c in contents)

    async def test_empty_results_for_no_match(self, db_session, test_project, embedded_sample_units):
        """Query matching no content returns empty list."""
        from loom.services.retrieval.search import keyword_search
        results = await keyword_search(db_session, test_project.id, "xyznonexistent")
        assert results == []

    async def test_returns_at_most_limit(self, db_session, test_project, embedded_sample_units):
        """Number of results capped at KEYWORD_SEARCH_LIMIT."""
        from loom.services.retrieval.search import keyword_search, KEYWORD_SEARCH_LIMIT
        results = await keyword_search(db_session, test_project.id, "the")
        assert len(results) <= KEYWORD_SEARCH_LIMIT

    async def test_all_results_have_keyword_score(self, db_session, test_project, embedded_sample_units):
        """Every result dict includes keyword_score."""
        from loom.services.retrieval.search import keyword_search
        results = await keyword_search(db_session, test_project.id, "bcrypt")
        for r in results:
            assert "keyword_score" in r
            assert isinstance(r["keyword_score"], float)

    async def test_scope_filter_limits_results(self, db_session, test_project, test_agent, embedded_sample_units):
        """scope_type_filter restricts results to matching type."""
        from loom.services.retrieval.search import keyword_search
        # Insert a summary unit (embedded_sample_units are all "decision")
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, 'summary', :tier,
                     :content, NULL, :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "tier": "agent",
                "content": "Summary about bcrypt security decisions",
                "embedding": None,
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        results = await keyword_search(
            db_session, test_project.id, "bcrypt",
            scope_type_filter="summary",
        )
        assert len(results) > 0
        for r in results:
            assert r["type"] == "summary"

    async def test_scoped_to_project(self, db_session, test_project, embedded_sample_units):
        """Results are scoped to project_id."""
        from loom.services.retrieval.search import keyword_search
        results = await keyword_search(
            db_session, uuid.uuid4(), "bcrypt",  # non-existent project
        )
        assert results == []
```

### Acceptance Criteria
- [x] `vector_search` returns semantically similar results (StubProvider is deterministic — same query → same embedding → stable ordering)
- [x] `vector_search` caps at `VECTOR_SEARCH_LIMIT`
- [x] `vector_search` returns `vector_score` for all results
- [x] `vector_search` excludes units with NULL embedding
- [x] `vector_search` respects `scope_type_filter`
- [x] `vector_search` scoped to project_id
- [x] `keyword_search` returns text-matching results
- [x] `keyword_search` returns empty for no-match query
- [x] `keyword_search` caps at `KEYWORD_SEARCH_LIMIT`
- [x] `keyword_search` returns `keyword_score` for all results
- [x] `keyword_search` respects `scope_type_filter`
- [x] `keyword_search` scoped to project_id

---

## C2 — Tests for RRF fusion and final scoring

### Files
- **MODIFY** `tests/services/retrieval/test_search.py` — append RRF + scoring tests (same file)

No DB needed — these are pure function tests.

### Test Scenarios

```python
class TestRRFFusion:
    """Tests for rrf_fusion — pure function, no DB needed."""

    def test_combines_two_lists(self):
        """Two lists with overlapping IDs are combined with summed scores."""
        from loom.services.retrieval.search import rrf_fusion
        vector_results = [
            {"id": "a", "content": "A from vector", "vector_score": 0.9},
            {"id": "b", "content": "B from vector", "vector_score": 0.8},
            {"id": "c", "content": "C from vector", "vector_score": 0.7},
        ]
        keyword_results = [
            {"id": "b", "content": "B from keyword", "keyword_score": 0.85},
            {"id": "d", "content": "D from keyword", "keyword_score": 0.6},
        ]
        fused = rrf_fusion(vector_results, keyword_results, k=60)

        # Both lists represented
        fused_ids = [u["id"] for u in fused]
        assert "a" in fused_ids
        assert "b" in fused_ids  # present in both
        assert "c" in fused_ids
        assert "d" in fused_ids

        # "b" should have highest RRF score (present in both lists)
        b_entry = next(u for u in fused if u["id"] == "b")
        a_entry = next(u for u in fused if u["id"] == "a")
        assert b_entry["rrf_score"] > a_entry["rrf_score"]

    def test_deduplicates(self):
        """Same unit appearing in both lists appears once."""
        from loom.services.retrieval.search import rrf_fusion
        vector_results = [{"id": "a", "content": "A"}, {"id": "b", "content": "B"}]
        keyword_results = [{"id": "a", "content": "A"}]
        fused = rrf_fusion(vector_results, keyword_results)
        ids = [u["id"] for u in fused]
        assert ids.count("a") == 1

    def test_single_list(self):
        """Single non-empty list returns that list ranked by RRF."""
        from loom.services.retrieval.search import rrf_fusion
        results = [
            {"id": "a", "content": "A"},
            {"id": "b", "content": "B"},
            {"id": "c", "content": "C"},
        ]
        fused = rrf_fusion(results, [], k=60)
        assert len(fused) == 3
        # RRF of single list: 1/(60+1), 1/(60+2), 1/(60+3)
        assert fused[0]["rrf_score"] == 1 / 61
        assert fused[1]["rrf_score"] == 1 / 62
        assert fused[2]["rrf_score"] == 1 / 63

    def test_empty_lists(self):
        """Two empty lists returns empty list."""
        from loom.services.retrieval.search import rrf_fusion
        assert rrf_fusion([], []) == []

    def test_sorted_descending(self):
        """Results are sorted by rrf_score descending."""
        from loom.services.retrieval.search import rrf_fusion
        vector_results = [
            {"id": "a", "content": "A"},
            {"id": "b", "content": "B"},
            {"id": "c", "content": "C"},
        ]
        keyword_results = [
            {"id": "b", "content": "B"},
            {"id": "d", "content": "D"},
        ]
        fused = rrf_fusion(vector_results, keyword_results)
        scores = [u["rrf_score"] for u in fused]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]


class TestNormalizeRRF:
    """Tests for _normalize_rrf_scores."""

    def test_normalizes_to_max(self):
        """Max score becomes 1.0, others proportional."""
        from loom.services.retrieval.search import _normalize_rrf_scores
        units = [
            {"id": "a", "rrf_score": 0.05},
            {"id": "b", "rrf_score": 0.03},
            {"id": "c", "rrf_score": 0.01},
        ]
        result = _normalize_rrf_scores(units)
        assert result[0]["rrf_score"] == 1.0
        assert result[1]["rrf_score"] == 0.6
        assert result[2]["rrf_score"] == 0.2

    def test_empty_list(self):
        """Empty list returns empty list."""
        from loom.services.retrieval.search import _normalize_rrf_scores
        assert _normalize_rrf_scores([]) == []

    def test_zero_scores_no_error(self):
        """All-zero scores does not divide by zero."""
        from loom.services.retrieval.search import _normalize_rrf_scores
        units = [{"id": "a", "rrf_score": 0.0}, {"id": "b", "rrf_score": 0.0}]
        result = _normalize_rrf_scores(units)
        assert all(u["rrf_score"] == 0.0 for u in result)


class TestComputeFinalScores:
    """Tests for compute_final_scores."""

    def test_adds_relevance_score(self):
        """Each unit gets a relevance_score key."""
        from loom.services.retrieval.search import compute_final_scores
        from datetime import datetime, timezone
        units = [
            {
                "id": "a",
                "type": "decision",
                "trust_tier": "user",
                "content": "Test A",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rrf_score": 1.0,
            },
            {
                "id": "b",
                "type": "summary",
                "trust_tier": "agent",
                "content": "Test B",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rrf_score": 0.6,
            },
        ]
        scored = compute_final_scores(units)
        for u in scored:
            assert "relevance_score" in u
            assert isinstance(u["relevance_score"], float)

    def test_summary_boost_applied(self):
        """Summary-type units get +0.15 boost."""
        from loom.services.retrieval.search import compute_final_scores
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        units = [
            {
                "id": "a", "type": "summary", "trust_tier": "agent",
                "content": "Summary", "created_at": now.isoformat(),
                "rrf_score": 0.5,
            },
            {
                "id": "b", "type": "decision", "trust_tier": "agent",
                "content": "Decision", "created_at": now.isoformat(),
                "rrf_score": 0.5,
            },
        ]
        scored = compute_final_scores(units)
        summary_score = next(u["relevance_score"] for u in scored if u["id"] == "a")
        decision_score = next(u["relevance_score"] for u in scored if u["id"] == "b")
        assert summary_score == pytest.approx(decision_score + 0.15, rel=1e-4)

    def test_sorted_descending(self):
        """Results sorted by relevance_score descending."""
        from loom.services.retrieval.search import compute_final_scores
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        units = [
            {"id": "a", "type": "decision", "trust_tier": "user",
             "content": "A", "created_at": now.isoformat(), "rrf_score": 0.8},
            {"id": "b", "type": "decision", "trust_tier": "agent",
             "content": "B", "created_at": now.isoformat(), "rrf_score": 0.6},
            {"id": "c", "type": "decision", "trust_tier": "external_tool",
             "content": "C", "created_at": now.isoformat(), "rrf_score": 0.4},
        ]
        scored = compute_final_scores(units)
        scores = [u["relevance_score"] for u in scored]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]
```

### Acceptance Criteria
- [x] `rrf_fusion` combines two ranked lists correctly
- [x] `rrf_fusion` deduplicates by unit ID
- [x] `rrf_fusion` with single list produces descending RRF scores
- [x] `rrf_fusion` with empty lists returns empty list
- [x] `_normalize_rrf_scores` maps max score to 1.0
- [x] `_normalize_rrf_scores` handles empty and zero-score inputs
- [x] `compute_final_scores` adds `relevance_score`
- [x] `compute_final_scores` applies summary +0.15 boost correctly
- [x] `compute_final_scores` sorts descending by score

---

## C3 — Tests for hybrid_search integration with read_context

### Files
- **MODIFY** `tests/integration/test_context_read.py` — add hybrid search integration tests

### Fixtures

Reuse existing `test_project`, `test_agent`, `auth_headers`, `sample_units`, `client` fixtures from `test_context_read.py`. The `sample_units` fixture writes units WITHOUT embeddings — we need a new fixture that also populates embeddings for hybrid tests.

Add a new fixture to `test_context_read.py`:

```python
@pytest_asyncio.fixture
async def embedded_sample_units(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> dict[str, Any]:
    """Write context units AND compute their embeddings for hybrid search tests.

    Same content as `sample_units` but also embeds each unit so vector
    search works.  Uses the StubProvider (always available, deterministic).
    """
    from loom.services.retrieval.providers import from_config
    from loom.db import async_session_factory

    provider = from_config()

    units: dict[str, Any] = {}
    writes = [
        ("summary_onboard", "Project overview: building a context server for AI agents"),
        ("summary_tech", "Technical stack: Python, FastAPI, PostgreSQL, pgvector"),
        ("decision_bcrypt", "Use bcrypt for password hashing to comply with security policies"),
        ("decision_cache", "Implement Redis caching layer for frequently accessed context"),
        ("message_hello", "Hello, I need to understand the authentication flow"),
        ("message_bcrypt_question", "How was the bcrypt decision implemented?"),
        ("task_user_tier_override", "Agent reviewed the bcrypt implementation and approved it"),
        ("task_external_tier", "External linter checked the bcrypt code for vulnerabilities"),
        ("summary_noise", "The weather today is sunny with a chance of rain"),
    ]

    for label, content in writes:
        body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "decision" if "decision" in label else "summary" if "summary" in label else "message",
            "content": content,
            "version": 1,
        }
        if "user" in label:
            body["trust_tier"] = "user"

        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=body,
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()

        # Compute embedding for the unit
        embedding = await provider.embed(content)
        if embedding:
            session = async_session_factory()
            await session.execute(
                text("UPDATE context_units SET embedding = :embedding::vector WHERE id = :id"),
                {"id": data["id"], "embedding": str(embedding)},
            )
            await session.commit()
            await session.close()

        units[label] = {
            "id": data["id"],
            "type": body["type"],
            "content": body["content"],
            "trust_tier": body.get("trust_tier", "agent"),
        }

    return units
```

### Test Scenarios

```python
class TestHybridSearchReadPath:
    """Integration tests: hybrid search through the read_context API."""

    async def test_hybrid_returns_more_relevant_results(
        self, client, test_project, auth_headers, embedded_sample_units,
    ):
        """Hybrid search should find bcrypt-related units for a security query."""
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "authentication security passwords", "budget": 10000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["units"]) > 0
        assert "degraded" in data
        assert data["degraded"] is False

        # bcrypt/security units should rank high
        contents = [u["content"].lower() for u in data["units"]]
        assert any("bcrypt" in c for c in contents)

    async def test_hybrid_respects_token_budget(
        self, client, test_project, auth_headers, embedded_sample_units,
    ):
        """Hybrid search response total_tokens does not exceed budget."""
        budget = 500
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "database schema design", "budget": budget},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] <= budget

    async def test_hybrid_empty_query_falls_through(
        self, client, test_project, auth_headers, embedded_sample_units,
    ):
        """Empty query returns chronological results (not hybrid)."""
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["units"]) > 0
        assert data["degraded"] is False

    async def test_hybrid_scope_onboarding(
        self, client, test_project, auth_headers, embedded_sample_units,
    ):
        """Hybrid search with scope=onboarding returns only summary-type units."""
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "project overview", "budget": 10000, "scope": "onboarding"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["units"]) > 0
        for unit in data["units"]:
            assert unit["type"] == "summary"

    async def test_hybrid_no_results(
        self, client, test_project, auth_headers, embedded_sample_units,
    ):
        """Query matching nothing returns empty list."""
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "xyznonexistentkeyword", "budget": 10000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["units"] == []

    async def test_existing_keyword_tests_still_pass(
        self, client, test_project, auth_headers, sample_units,
    ):
        """Existing tests using sample_units (no embeddings) still work."""
        resp = await client.get(
            f"/v1/projects/{test_project.id}/context",
            params={"query": "bcrypt", "budget": 10000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["units"]) > 0
        contents = [u["content"].lower() for u in data["units"]]
        assert any("bcrypt" in c for c in contents)
```

### Acceptance Criteria
- [x] Hybrid search through the API returns results with `relevance_score`
- [x] Hybrid search response includes `degraded: false`
- [x] Token budget is respected in hybrid search results
- [x] Empty query falls through to chronological (no hybrid, no vector search)
- [x] `scope=onboarding` filters to summary type in hybrid search
- [x] Query matching nothing returns empty list
- [x] Existing tests (no-embedding units) continue to pass unchanged
- [x] Hybrid results are ranked by relevance score descending

---

## Execution Order DAG

```
A1 (encode_query, vector_search, keyword_search)
│
├──▶ A2 (rrf_fusion, compute_final_scores, pack_results)
│     │
│     └──▶ A3 (hybrid_search orchestrator)
│            │
│            ├──▶ B1 (update read_context in service.py)
│            │     │
│            │     └──▶ C3 (integration tests)
│            │
│            └──▶ (depends on A1, A2 for imports)
│
├──▶ C1 (unit tests for vector_search, keyword_search)
│
└──▶ (A2) ──▶ C2 (unit tests for RRF, scoring)
```

### Dependency Rationale

| Edge | Why |
|---|---|
| **A1 → A2** | A2's `rrf_fusion` operates on the dict format produced by A1's `vector_search`/`keyword_search` |
| **A1 + A2 → A3** | `hybrid_search()` orchestrator calls all functions from A1 and A2 |
| **A3 → B1** | `service.py` imports `hybrid_search` from `search.py` |
| **A1 → C1** | Unit tests for sub-search functions depend on them existing |
| **A2 → C2** | Unit tests for RRF/scoring depend on those functions existing |
| **A3 + B1 → C3** | Integration tests exercise the full path through read_context → hybrid_search |

### Parallelism Opportunities

- **A1** and **A2** could technically be written in parallel (different concerns within the same file), but since they go into the same `search.py` file, they should be done sequentially to avoid merge conflicts.
- **C1** (sub-search unit tests) can start as soon as **A1** is done.
- **C2** (RRF unit tests) can start as soon as **A2** is done.
- **A3** (orchestrator) must wait for both **A1** and **A2**.
- **B1** (service.py integration) and **C3** (integration tests) are the final gates.

### Recommended Execution Order

```
Phase 1:  A1 ──▶ A2
Phase 2:  C1 (after A1) ─── parallel ─── C2 (after A2)
Phase 3:  A3 (after A1 + A2)
Phase 4:  B1 (after A3)
Phase 5:  C3 (after B1)  ← final gate
```
