---
title: "Phase 1.11 — Basic Browser UI (Read-Only Feed)"
description: "A simple browser-based chat interface showing a live WebSocket feed of context units with provenance and trust-tier display."
status: pending
dependencies: ["phase-1/02-context-service-write.md", "phase-1/07-trust-tier.md"]
---

# Basic Browser UI (Read-Only Feed)

## Description
Build a simple browser-based UI that connects to Loom via WebSocket and displays a live feed of context units as they are written. Each unit shows: agent, type, trust tier, content preview, and parent references. This is the "window" into the shared context.

## Location
All files under `web/`.

## Files to Create
- `web/index.html` — single-page application
- `web/style.css` — styling
- `web/app.js` — application logic (WebSocket, rendering, state)

## WebSocket Endpoint

### Gateway Handler (`api/websocket/handler.py`)

```
GET /v1/projects/{project_id}/events (WebSocket upgrade)
```

The WebSocket handler:
1. Authenticates the connection (token in query string)
2. Subscribes to project events via Redis pub/sub
3. Forwards events to the browser client as JSON

Event format:
```json
{
    "event": "context_unit_written",
    "data": {
        "id": "uuid",
        "type": "decision",
        "trust_tier": "agent",
        "agent_id": "uuid",
        "content_preview": "Decision: use bcrypt...",
        "created_at": "2026-07-23T12:00:00Z",
        "parent_ids": ["uuid1"]
    }
}
```

### Redis Pub/Sub Integration
In the write path, after committing:
```python
await redis.publish(f"project:{project_id}:events", json.dumps(event_data))
```

## UI Implementation

### HTML Structure
```
┌─────────────────────────────────────────┐
│  Loom — Project: "My Project"    [⚙]    │
├─────────────────────────────────────────┤
│                                         │
│  ┌─ Context Unit ─────────────────────┐ │
│  │  [agent] [decision] [🤖]           │ │
│  │  Decision: Use bcrypt for          │ │
│  │  password hashing                  │ │
│  │  ─────────────────────────────     │ │
│  │  Derived from: UI design spec      │ │
│  │  Created: 2s ago by agent-42       │ │
│  └────────────────────────────────────┘ │
│                                         │
│  ┌─ Context Unit ─────────────────────┐ │
│  │  [user] [message] [👤]             │ │
│  │  Let's use bcrypt for auth         │ │
│  │  ─────────────────────────────     │ │
│  │  Created: 5s ago by user@email.com │ │
│  └────────────────────────────────────┘ │
│                                         │
│  ┌─ Detail Pane ──────────────────────┐ │
│  │  (click on a unit to expand)        │ │
│  │  Full content, all metadata,        │ │
│  │  link to parents/children           │ │
│  └────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│  Connected | 42 units | 3 agents active │
└─────────────────────────────────────────┘
```

### Key Features
- **Live feed**: New context units appear at the top in real time (no page refresh)
- **Trust tier badges**: Color-coded: user (green), agent (blue), external_tool (gray)
- **Type icons**: Different icons for message, decision, artifact_ref, task_result, summary
- **Click to expand**: Show full content + all metadata in a detail pane
- **Agent indicator**: Show which agent wrote each unit
- **Connection status**: Show connected/reconnecting/disconnected state
- **Auto-scroll**: Optionally auto-scroll to show newest units

## Acceptance Criteria

- [ ] UI connects to WebSocket and shows live events
- [ ] New context units appear without page refresh
- [ ] Trust tier colors are displayed correctly (green/blue/gray)
- [ ] Clicking a unit shows full content and metadata
- [ ] Connection status shows connected/reconnecting states
- [ ] UI works in Chrome, Firefox, and Safari
- [ ] Events are broadcast to all connected clients (multi-user)
- [ ] Page loads and works with just `python -m http.server web/` (static files)

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_websocket_receives_write_events(client, test_project, ws_client):
    # Connect WebSocket
    async with ws_client.connect(f"/v1/projects/{test_project}/events") as ws:
        # Write a context unit
        await client.post(f"/v1/projects/{test_project}/context", json={
            "client_uuid": str(uuid4()),
            "type": "message",
            "content": "WebSocket test",
            "version": 1
        })
        # Verify event is received via WebSocket
        event = await ws.receive_json()
        assert event["event"] == "context_unit_written"

@pytest.mark.asyncio
async def test_multiple_clients_receive_same_event(client, test_project, ws_client):
    # Two WebSocket connections should both receive the event
    pass
```

## Dependencies
- Phase 1.2 (write path — produces events to broadcast)
- Phase 1.7 (trust-tier — needed for badge display)
- Redis (for pub/sub event broadcasting)
