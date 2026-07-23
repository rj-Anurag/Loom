---
title: "Phase 2.3 — Hybrid Search (Vector + Keyword)"
description: "Combine pgvector ANN search with GIN full-text search using reciprocal-rank fusion for relevance-ranked retrieval."
status: pending
dependencies: ["phase-1/03-context-service-read.md", "phase-1/09-embedding-pipeline.md"]
---

# Hybrid Search

## Description
Upgrade the naive keyword-only retrieval from Phase 1.3 to a hybrid search that combines vector similarity (pgvector ANN) with keyword full-text search (GIN index) using Reciprocal Rank Fusion (RRF). This gives both semantic and exact-match results.

## Hybrid Search Algorithm

### 1. Vector Search
```sql
SELECT id, content, type, trust_tier, created_at,
       1 - (embedding <=> $query_embedding) AS vector_score
FROM context_units
WHERE project_id = $1
  AND embedding IS NOT NULL
ORDER BY embedding <=> $query_embedding
LIMIT 50;
```

### 2. Keyword Search
```sql
SELECT id, content, type, trust_tier, created_at,
       ts_rank(to_tsvector('english', content), plainto_tsquery('english', $query)) AS keyword_score
FROM context_units
WHERE project_id = $1
  AND to_tsvector('english', content) @@ plainto_tsquery('english', $query)
ORDER BY keyword_score DESC
LIMIT 50;
```

### 3. Reciprocal Rank Fusion (RRF)
```python
def rrf(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """
    Combine multiple ranked lists using RRF.
    score(item) = SUM(1 / (k + rank(item)))
    """
    scores = {}
    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list, start=1):
            item_id = item["id"]
            scores[item_id] = scores.get(item_id, 0) + 1 / (k + rank)
    
    # Merge results with scores
    result = []
    seen = set()
    for ranked_list in ranked_lists:
        for item in ranked_list:
            if item["id"] not in seen:
                seen.add(item["id"])
                item["rrf_score"] = scores[item["id"]]
                result.append(item)
    
    result.sort(key=lambda x: x["rrf_score"], reverse=True)
    return result
```

### 4. Final Ranking
Combine RRF score with trust-tier weight and recency:
```python
final_score = 0.6 * rrf_score
            + 0.2 * trust_tier_weight(unit.trust_tier)
            + 0.2 * recency_score(unit.created_at)
```

## Token-Budget-Aware Packing

After ranking, pack results into the requested token budget:

```python
async def pack_results(units: list[dict], budget: int) -> list[dict]:
    """
    Pack ranked units into the token budget.
    - Start with highest-scored units
    - Truncate content of low-scored units if needed
    - Include all summary units (they're small and high-value)
    """
    packed = []
    tokens_used = 0
    for unit in units:
        unit_tokens = estimate_tokens(unit["content"])
        if tokens_used + unit_tokens <= budget:
            packed.append(unit)
            tokens_used += unit_tokens
        else:
            # Truncate content to fit remaining budget
            remaining = budget - tokens_used
            unit["content"] = truncate_to_budget(unit["content"], remaining)
            unit["truncated"] = True
            packed.append(unit)
            break
    return {"units": packed, "total_tokens": tokens_used, "truncated": tokens_used < sum_tokens}
```

## Embedding Query Encoding
The query itself must be converted to a vector using the same embedding model:

```python
async def encode_query(query: str) -> list[float]:
    if settings.EMBEDDING_PROVIDER == "openai":
        resp = await openai.Embedding.acreate(model="text-embedding-ada-002", input=query)
        return resp["data"][0]["embedding"]
    else:
        return await compute_embedding(query)  # same function as Phase 1.9
```

## File Targets
- `services/retrieval/search.py` — hybrid search implementation
  - `vector_search()`
  - `keyword_search()`
  - `hybrid_search()` — combines both with RRF
  - `pack_results()` — token-budget-aware packing
- `services/context/service.py` — update `read_context()` to use hybrid search

## Acceptance Criteria
- [ ] Vector search returns semantically similar results
- [ ] Keyword search returns exact-match results
- [ ] Hybrid search combines both into a single ranked list
- [ ] RRF correctly balances vector and keyword scores
- [ ] Token budget is respected in the final result
- [ ] Summary-type units are always included (even if over budget)
- [ ] Response time < 500ms for hybrid queries

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_vector_search_returns_semantic_results(search_service, sample_units):
    query = "authentication security"
    results = await search_service.vector_search("test-project", query)
    assert len(results) > 0

@pytest.mark.asyncio
async def test_hybrid_search_combines_results(search_service, sample_units):
    query = "database schema design"
    results = await search_service.hybrid_search("test-project", query, budget=2000)
    assert len(results["units"]) > 0
    assert results["total_tokens"] <= 2000

@pytest.mark.asyncio
async def test_token_budget_truncation(search_service, sample_units):
    query = "test"
    results = await search_service.hybrid_search("test-project", query, budget=100)
    assert results["total_tokens"] <= 100
```

## Dependencies
- Phase 1.3 (read path exists, needs upgrade)
- Phase 1.9 (embedding pipeline populates embedding vectors)
