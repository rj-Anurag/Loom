---
title: "Phase 1.3 — Context Service: Read Path"
description: "REST endpoint GET /v1/projects/{id}/context that retrieves context units with keyword filtering and token-budget-aware packing."
status: completed
dependencies: ["phase-1/02-context-service-write.md"]
---

# Context Service: Read Path

## Description
Implement the read side of the Context Service. When an agent requests context, the service retrieves relevant context units, filters them by the query, packs them into the requested token budget (prioritizing recent and higher-trust-tier units), and returns them as a ranked bundle.

## Location
`services/context/service.py` — `read_context()` function
`api/routes/context.py` — GET handler

## API Specification

```
GET /v1/projects/{project_id}/context?query=...&budget=...&scope=...
Authorization: Bearer <agent-api-key>

Query Parameters:
- query: string (natural language description of what the agent needs)
- budget: integer (max tokens to return, default 4096, max 32000)
- scope: string (optional: "onboarding" | "task" | "full", default "task")

Response 200:
{
    "units": [
        {
            "id": "uuid",
            "type": "message|decision|artifact_ref|task_result|summary",
            "trust_tier": "user|agent|external_tool",
            "content": "truncated content...",
            "created_at": "2026-07-23T12:00:00Z",
            "agent_id": "uuid",
            "parent_ids": ["uuid1"],
            "relevance_score": 0.92
        }
    ],
    "total_tokens": 4096,
    "budget_used": 4096,
    "truncated": false
}
```

## Implementation (v1 — Naive, No Embeddings Yet)

For Phase 1, implement a keyword-based retrieval that does NOT require embeddings:
1. Parse the `query` into keywords (tokenize + stem)
2. Search `context_units` using the GIN full-text index on `content`
3. Rank results by: (a) keyword match density, (b) recency, (c) trust_tier weight
4. Pack results into the token budget, truncating content if needed
5. Prefer `summary`-type units, then `decision`, then `message`
6. If `scope=onboarding`, return only summary-type units + project overview

Token counting: use a simple approximation (4 chars ~= 1 token, or use tiktoken if Python).

## Ranking Formula (v1)
```
score = 0.4 * ts_rank(textsearch, query)
      + 0.3 * (1.0 / (hours_since_creation + 1))
      + 0.3 * trust_tier_weight(user=1.0, agent=0.7, external_tool=0.4)
```

## File Targets
- `services/context/service.py` — add `read_context()` function
- `api/routes/context.py` — add GET handler

## Acceptance Criteria

- [ ] GET returns context units matching the keyword query
- [ ] Results are ordered by relevance (best match first)
- [ ] Token budget is respected (total response tokens <= budget)
- [ ] Trust-tier weighting works: user-authored content ranks above agent-authored
- [ ] `scope=onboarding` returns only summary-type units
- [ ] Empty query returns most recent units
- [ ] No results returns empty array (not 404)
- [ ] Response time < 300ms for typical queries on a small dataset

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_read_context_returns_units(client, test_project, sample_units):
    resp = await client.get(f"/v1/projects/{test_project}/context?query=hello&budget=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["units"]) > 0

@pytest.mark.asyncio
async def test_read_context_respects_budget(client, test_project, sample_units):
    resp = await client.get(f"/v1/projects/{test_project}/context?query=hello&budget=100")
    data = resp.json()
    assert data["total_tokens"] <= 100

@pytest.mark.asyncio
async def test_read_context_empty_query(client, test_project, sample_units):
    resp = await client.get(f"/v1/projects/{test_project}/context")
    assert resp.status_code == 200
```

## Dependencies
- Phase 1.1 (database schema with GIN index)
- Phase 1.2 (write path must work to populate test data)
