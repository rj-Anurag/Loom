---
title: "Phase 2.5 — Interactive Browser UI"
description: "Upgrade the read-only browser feed to an interactive UI: context graph browser, merge conflict resolution, task creation, and agent management."
status: pending
dependencies: ["phase-1/11-browser-ui-feed.md", "phase-2/04-live-presence.md"]
---

# Interactive Browser UI

## Description
Upgrade the read-only browser feed from Phase 1.11 into a full interactive dashboard. Users can: browse the context graph, resolve merge conflicts, create tasks for agents, inspect provenance, and see live agent presence.

## Features

### 1. Context Graph Browser
Visualize the context unit DAG as an interactive graph:
- Nodes = context units (color-coded by type and trust-tier)
- Edges = relationships (derived_from, supersedes, references, merged_from)
- Click a node to expand full content and metadata
- Zoom and pan navigation
- Filter by type, trust-tier, agent, time range

Uses a lightweight graph visualization library (e.g., vis-network or d3.js).

### 2. Merge Conflict Resolution UI
When conflicts are flagged, show them in an interactive diff view:
```
┌─ Conflicts ──────────────────────────┐
│                                       │
│  ⚠ Pending Conflict #42               │
│  ┌─ Agent A's version ──┐ ┌─ Agent ──┐│
│  │ Use JWT for auth      │ │ Use OAuth││
│  └───────────────────────┘ └──────────┘│
│                                       │
│  [Accept A] [Accept B] [Merge]        │
│                                       │
│  ┌─ Merged Result ─────────────────┐  │
│  │ (editable text area)             │  │
│  └──────────────────────────────────┘  │
│                                       │
└───────────────────────────────────────┘
```

Resolution options:
- **Accept A**: Keep Agent A's version
- **Accept B**: Keep Agent B's version  
- **Merge**: Combine both (user edits the merged result)
- Resolution is written as a new context unit with `merged_from` edges

### 3. Task Creation & Management
Form to create tasks for agents:
```
┌─ Create Task ─────────────────────────┐
│ Title: [                             ] │
│ Description: [                       ] │
│   [textarea]                           │
│ Assign to: [ ▼ Select agent...     ]  │
│ Priority: [ ▼ Medium               ]  │
│                                       │
│ [Create Task]                          │
└───────────────────────────────────────┘
```

Task list shows: status, assigned agent, created time, completion time.

### 4. Agent Management Panel
```
┌─ Active Agents ───────────────────────┐
│                                       │
│  🟢 Agent Alpha (local)               │
│     Working on: Auth design           │
│     Heartbeat: 3s ago                 │
│     Locks held: 2                     │
│                                       │
│  🟡 Agent Beta (cloud)                │
│     Status: Idle                      │
│     Heartbeat: 12s ago                │
│                                       │
│  🔴 Agent Gamma (browser)             │
│     Status: Offline                   │
│     Last seen: 2m ago                 │
│                                       │
└───────────────────────────────────────┘
```

### 5. Provenance Inspector
Full context unit details panel:
- Full content (not truncated)
- All metadata (id, type, trust_tier, agent, version, branch, timestamps)
- Parent units (clickable, linked)
- Child units (clickable, linked)
- Event log entries related to this unit
- Trust tier indicator with explanation

## File Targets
- `web/index.html` — complete rewrite with interactive features
- `web/style.css` — expanded styles for all new components
- `web/app.js` — application logic, API calls, WebSocket handling
- `web/graph.js` — context graph visualization
- `web/conflict.js` — merge conflict resolution UI
- `web/tasks.js` — task management panel
- `web/agents.js` — agent management panel

## Acceptance Criteria
- [ ] Context graph loads and is navigable (zoom, pan, click)
- [ ] Merge conflicts are displayed with A/B/merge options
- [ ] Conflict resolution writes a new context unit
- [ ] Tasks can be created, assigned, and tracked
- [ ] Agent presence shows live status updates
- [ ] Provenance inspector shows all metadata for any unit
- [ ] UI works in Chrome, Firefox, Safari
- [ ] All API calls are authenticated

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_conflict_resolution_endpoint(client, test_project, sample_conflict):
    resp = await client.post(
        f"/v1/projects/{test_project}/conflicts/{sample_conflict.id}/resolve",
        json={"resolution": "accept_a"}
    )
    assert resp.status_code == 200
```

## Dependencies
- Phase 1.11 (basic browser UI exists to upgrade)
- Phase 2.4 (live presence for agent management panel)
