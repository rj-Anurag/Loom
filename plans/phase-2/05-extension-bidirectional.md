---
title: "Phase 2.5 — Browser Extension (Bidirectional)"
description: "Extend the browser extension to show live agent activity, pending conflicts, and project status in a sidebar panel — and push decisions from the browser back to the Loom context store."
status: pending
dependencies: ["phase-1/11-browser-extension-core.md", "phase-2/04-live-presence.md"]
---

# Browser Extension (Bidirectional)

## Description
Upgrade the basic browser extension from Phase 1.11 into a bidirectional bridge. The extension adds a sidebar panel that shows live agent activity (what agents are doing, their status, recent context writes), pending merge conflicts, and project status — all without leaving the browser chat. Users can also manually push decisions from the browser chat into Loom as high-trust context units.

## Features

### 1. Agent Activity Sidebar
A collapsible sidebar panel within the extension popup that shows:
```
┌─ Loom Project: "auth" ─────────────────┐
│                                         │
│  🟢 Agent Alpha (local)                 │
│     Working on: "Password hashing"      │
│     Last write: 2s ago (decision)       │
│     Heartbeat: 3s ago                   │
│                                         │
│  🟡 Agent Beta (cloud)                  │
│     Status: Idle                         │
│     Last write: 12s ago (task_result)   │
│     Heartbeat: 7s ago                   │
│                                         │
│  [Show recent context] [Refresh]        │
└─────────────────────────────────────────┘
```

### 2. Live Context Feed (Sidebar)
A scrollable feed of recent context units written by all agents:
- New entries appear in real time (via WebSocket or polling)
- Color-coded by trust tier (user=green, agent=blue, external_tool=gray)
- Click to expand full content
- Filter by type, agent, trust tier

### 3. Conflict Notifications
When the Loom coordination system detects a merge conflict:
- Badge count on extension icon (e.g., "3")
- Sidebar shows pending conflicts with summary
- Click to see A/B versions inline

### 4. Push-to-Loom from Chat
Users can manually select a portion of the browser chat and push it to Loom:
- Right-click → "Send to Loom as context"
- Prompts for type (decision, message, artifact_ref) and trust tier
- Calls the Loom write API with the selected text

### 5. Project Dashboard View
Full-page dashboard accessible from extension popup:
- Project overview: agent count, context unit count, last activity
- Recent context feed (full scrollable list)
- Agent status dashboard
- Pending conflicts queue
- Link/unlink chats from this project

## File Targets
- `extension/background.js` — expanded: WebSocket connections, push-from-chat, conflict polling
- `extension/popup.html` — expanded with agent activity sidebar
- `extension/popup.js` — expanded with activity rendering, conflict list
- `extension/dashboard.html` — full-page project dashboard
- `extension/dashboard.js` — dashboard logic
- `extension/config.js` — updated with WebSocket endpoint config

## API Endpoints Needed

### WebSocket Feed (agent activity)
```
GET /v1/projects/{project_id}/events (WebSocket upgrade)
```
Events: `context_unit_written`, `conflict_flagged`, `agent_status_changed`

### Conflict List
```
GET /v1/projects/{project_id}/conflicts?status=pending
```

### Push from Chat
Uses the existing write endpoint:
```
POST /v1/projects/{project_id}/context
```

## Acceptance Criteria
- [ ] Extension sidebar shows live agent activity (name, status, last action)
- [ ] Recent context feed shows entries from all agents in real time
- [ ] Conflict badge count appears on extension icon
- [ ] Pending conflicts are viewable in the sidebar
- [ ] Right-click → "Send to Loom" pushes selected text as a context unit
- [ ] Dashboard page loads and shows project overview
- [ ] WebSocket reconnects automatically on disconnect
- [ ] All API calls are authenticated

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_websocket_agent_events(client, test_project, ws_client):
    """WebSocket delivers agent_status_changed events."""
    async with ws_client.connect(f"/v1/projects/{test_project}/events") as ws:
        event = await ws.receive_json()
        assert event["event"] in ("context_unit_written", "agent_status_changed", "conflict_flagged")

@pytest.mark.asyncio
async def test_conflict_list_endpoint(client, test_project, sample_conflict):
    """GET /v1/projects/{id}/conflicts returns pending conflicts."""
    resp = await client.get(f"/v1/projects/{test_project}/conflicts?status=pending")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
```

## Dependencies
- Phase 1.11 (basic extension exists to upgrade)
- Phase 2.1 (full coordination — needed for conflict list)
- Phase 2.4 (live presence — needed for agent heartbeat sidebar)
- Phase 1.2 (context write path — needed for push-from-chat)
