---
title: "Phase 1.11 — Browser Extension (Core)"
description: "A browser extension that detects AI chats, links them to Loom projects, and auto-syncs messages as context units for retrieval via the @loom CLI command."
status: pending
dependencies: ["phase-1/02-context-service-write.md", "phase-1/07-trust-tier.md"]
---

# Browser Extension (Core)

## Description
Build a browser extension that bridges AI chat platforms (Claude.ai, ChatGPT) with Loom. The extension detects when a user opens a chat, offers a one-tap link to a Loom project, then auto-syncs chat messages into Loom's context store. Developers can later retrieve this context in their CLI via `@loom <prompt>` — no manual copy-paste required.

## Location
All files under `extension/`.

## Files to Create
- `extension/manifest.json` — extension manifest (Chrome/Edge/Firefox)
- `extension/content.js` — content script for chat platform detection
- `extension/popup.html` — one-tap linking popup UI
- `extension/popup.js` — popup logic (project list, link, status)
- `extension/background.js` — background service worker (sync manager, API calls)
- `extension/storage.js` — Chrome local storage helper (URL → project_id mapping)
- `extension/config.js` — config (Loom server URL, supported platforms)

## Linking Strategy

### One-Tap Manual Linking (MVP)

```
1. User opens a chat on Claude.ai
2. Extension checks if this chat URL is already linked to a Loom project
3. If not linked → show one prompt (once ever per chat):

   ┌──────────────────────────────────────────────────┐
   │ 📁  Link "Event Log Design" to a Loom project?   │
   │                                                   │
   │  ○  loom-auth (match by title)                     │
   │  ○  <other recent projects>                       │
   │  ○  Create new project → "Event Log Design"       │
   │  ○  Not now / Never for this chat                 │
   └──────────────────────────────────────────────────┘

4. User picks → remembered in Chrome local storage (keyed by chat URL)
5. Zero-effort auto-sync from that point forward
```

- One tap per chat, never again
- Deterministic linking — no false positives from fuzzy matching
- Storage: `chrome.storage.local` — URL string → project_id UUID

### What Gets Synced

| Event | Action |
|---|---|
| User opens chat | Extension checks if URL is linked to a project |
| User types / AI responds | Captures each message pair as a context_unit |
| User makes a decision | Detects decision patterns → tags as `decision` type |
| User closes chat | Flushes remaining unsynced messages |
| Next `@loom` prompt | CLI retrieves synced context automatically |

### Platform Priority
1. **Claude.ai** — dogfood first
2. **ChatGPT** — largest user base after Claude
3. Any AI chat platform — each new platform = new content script, identical linking logic

## Architecture

```
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│  Browser Chat     │        │  Loom Extension   │        │  Loom Context     │
│  (Claude.ai)      │───────▶│  (Content Script)  │───────▶│  Server (Daemon)  │
│                   │        │                   │        │                   │
│  User & AI chat   │        │  Detect → Link     │        │  Store & index    │
│  about "auth"     │        │  → Sync → Done     │        │  → Serve via MCP  │
└──────────────────┘        └──────────────────┘        └────────┬───────────┘
                                                                   │
                                                                   ▼
                                                         ┌──────────────────┐
                                                         │  CLI Tool         │
                                                         │  (Claude Code,    │
                                                         │   opencode, etc.) │
                                                         │                   │
                                                         │  @loom <prompt>   │
                                                         │  → context        │
                                                         │    injected       │
                                                         └──────────────────┘
```

## API Endpoints Needed

The extension calls the Loom context server API:

### Link Chat to Project
```
POST /v1/projects/{project_id}/link/chat
{
    "chat_url": "https://claude.ai/chat/abc123",
    "title": "Event Log Design",
    "platform": "claude.ai"
}
```

### Sync Messages
```
POST /v1/projects/{project_id}/context
{
    "client_uuid": "<stable-id-derived-from-chat-url+message-index>",
    "type": "message",
    "content": "User: Let's use bcrypt for auth\nAI: Good choice...",
    "trust_tier": "user",
    "branch_id": "<chat-session-id>"
}
```

### List User Projects
```
GET /v1/projects
```

### Create Project
```
POST /v1/projects
{
    "name": "Event Log Design",
    "retention_policy": "archive_after_90_days"
}
```

## Acceptance Criteria

- [ ] Extension detects when user is on Claude.ai chat page
- [ ] One-tap link popup appears for unlinked chats (once per chat)
- [ ] Project list loads in the popup from Loom API
- [ ] Chat messages sync to Loom context store automatically after linking
- [ ] Synced messages are retrievable via `@loom <prompt>` in CLI
- [ ] Extension works in Chrome (MVP), Firefox planned
- [ ] Linking persists across browser sessions (stored in chrome.storage.local)
- [ ] Sync is idempotent (same message synced twice = no duplicate via client_uuid)
- [ ] Extension shows connection status to Loom server

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_link_chat_endpoint(client, test_project):
    """POST /v1/projects/{id}/link/chat stores the link."""
    resp = await client.post(
        f"/v1/projects/{test_project}/link/chat",
        json={"chat_url": "https://claude.ai/chat/abc123", "title": "Test", "platform": "claude.ai"}
    )
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_list_projects_for_popup(client, test_project):
    """GET /v1/projects returns projects for the popup dropdown."""
    resp = await client.get("/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
```

## Dependencies
- Phase 1.2 (context write path — needed for syncing messages)
- Phase 1.6 (idempotency via client_uuid — prevents duplicate syncs)
- Loom context server must be running and reachable from the browser
