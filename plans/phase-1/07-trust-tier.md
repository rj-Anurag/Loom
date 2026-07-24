---
title: "Phase 1.7 — Trust-Tier Field"
description: "Trust-tier ENUM on every Context Unit. Propagation through read/write. Retrieval weighting by trust tier."
status: completed
dependencies: ["phase-1/01-db-schema.md", "phase-1/02-context-service-write.md", "phase-1/03-context-service-read.md"]
---

# Trust-Tier Field

## Description
Every Context Unit carries a `trust_tier` field indicating the trustworthiness of its source. This is critical for cross-agent safety: an agent reading context should know whether the content was written by a human user, a peer agent, or an external tool, and weight its trust accordingly.

## Trust Tier Values

| Value | Source | Typical Content | Confidence |
|---|---|---|---|
| `user` | Human user via extension popup or direct input | Requirements, decisions, approvals | Highest — user intent |
| `agent` | AI agent (local, cloud, or browser) | Task results, analysis, messages | Medium — agent may be wrong |
| `external_tool` | Automated tool or external system | CI results, webhook data, logs | Lowest — unverified source |

## Implementation

### Schema
Already included in Phase 1.1:
```sql
CREATE TYPE trust_tier AS ENUM ('user', 'agent', 'external_tool');
ALTER TABLE context_units ADD COLUMN trust_tier trust_tier NOT NULL DEFAULT 'agent';
```

### Write Path
- The `trust_tier` is set by the writing agent/client
- Agents should default to `agent` tier (set by MCP tool wrapper)
- Human UI sessions default to `user` tier
- External integrations default to `external_tool` tier
- Agents CANNOT write at a higher trust tier than their authenticated identity allows
  - An agent cannot impersonate `user` tier
  - The auth middleware enforces this mapping

### Read Path (Retrieval Weighting)
The retrieval ranking formula (from Phase 1.3) incorporates trust tier:

```
score = 0.3 * keyword_relevance
      + 0.2 * recency
      + 0.3 * trust_tier_weight
      + 0.2 * context_graph_proximity
```

Trust tier weights:
- `user` = 1.0
- `agent` = 0.7
- `external_tool` = 0.4

### Query Parameter
The `read_context` MCP tool accepts an optional `min_trust_tier` parameter:
- Default: `external_tool` (return everything)
- `agent`: exclude `external_tool` content
- `user`: return only human-authored content

### Trust Tier in the Extension
The browser extension popup/feed must display the trust tier visually:
- `user` = green badge
- `agent` = blue badge
- `external_tool` = gray badge

## File Targets
- `services/context/service.py` — enforce trust tier in write validation
- `services/context/service.py` — add trust tier weight to read ranking
- `api/middleware.py` — map auth identity to allowed trust tiers
- `services/context/mcp_tools.py` — add `min_trust_tier` parameter to read_context
- `extension/popup.js` — display trust tier badges in extension feed

## Acceptance Criteria

- [ ] Write without trust_tier defaults to `agent`
- [ ] Agent cannot write with `user` trust tier
- [ ] `read_context` with `min_trust_tier=user` returns only user-authored content
- [ ] Retrieval ranking weights trust_tier correctly
- [ ] Extension popup displays trust tier badge for every context unit
- [ ] Trust tier is preserved through the entire write-read cycle

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_default_trust_tier_is_agent(client, test_project):
    body = {"client_uuid": str(uuid4()), "type": "message", "content": "test", "version": 1}
    resp = await client.post(f"/v1/projects/{test_project}/context", json=body)
    unit_id = resp.json()["id"]
    unit = await db.fetchrow("SELECT * FROM context_units WHERE id = $1", unit_id)
    assert unit["trust_tier"] == "agent"

@pytest.mark.asyncio
async def test_agent_cannot_write_user_tier(client, test_project):
    body = {"client_uuid": str(uuid4()), "type": "message", "content": "test",
            "trust_tier": "user", "version": 1}
    resp = await client.post(f"/v1/projects/{test_project}/context", json=body)
    assert resp.status_code == 403

@pytest.mark.asyncio
async def test_min_trust_tier_filter(client, test_project, sample_units):
    resp = await client.get(
        f"/v1/projects/{test_project}/context?query=test&min_trust_tier=user"
    )
    units = resp.json()["units"]
    assert all(u["trust_tier"] == "user" for u in units)
```

## Dependencies
- Phase 1.1 (trust_tier column in schema)
- Phase 1.2 (write path)
- Phase 1.3 (read path)
