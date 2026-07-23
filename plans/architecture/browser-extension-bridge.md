# Browser Extension Bridge

The bridge between browser AI chats (Claude.ai, ChatGPT, etc.) and the Loom context layer.

## The Problem

Browser chats and CLI agents exist in separate contexts. Users design architecture in Claude.ai, then open the CLI to implement it — but the CLI has zero awareness of what was discussed. Manual copy-paste is the current workaround.

## The Solution

A browser extension that syncs chat content into Loom's context store automatically. When the user later types `@loom <prompt>` in their CLI, Loom retrieves this synced context and injects it into the prompt — no manual pasting required.

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

## Linking Strategy

### Primary: Manual one-tap (MVP)

```
1. User opens a chat on Claude.ai
2. Extension checks if this chat URL is already linked to a Loom project
3. If not linked → show one prompt (once ever per chat):

   ┌──────────────────────────────────────────────────┐
   │ 📁  Link "Event Log Design" to a Loom project?   │
   │                                                   │
   │  ○  loom-auth (match by title)                    │
   │  ○  <other recent projects>                       │
   │  ○  Create new project → "Event Log Design"       │
   │  ○  Not now / Never for this chat                 │
   └──────────────────────────────────────────────────┘

4. User picks → remembered in extension storage (keyed by chat URL)
5. Zero-effort auto-sync from that point forward
```

- One tap per chat, never again
- Deterministic — no false positives
- Works day one
- Storage: Chrome local storage (URL → project_id mapping)

### Secondary: Agent-driven categorization (post-MVP)

A Loom agent periodically scans unlinked chats and proposes groupings.

### Skipped: Full-auto fuzzy embedding match

Fuzzy matching via pgvector embeddings is a Phase 2 concern. It requires the embedding pipeline and similarity search infra before it can work — infrastructure that doesn't exist yet and adds complexity with imperfect results.

## Platform Priority

1. **Claude.ai** — dogfood first
2. **ChatGPT** — largest user base after Claude
3. Any AI chat platform — each new platform = new content script, identical linking logic

## What the Extension Does

| Event | Action |
|---|---|
| User opens chat | Extension checks if URL is linked to a project |
| User types / AI responds | Captures each message pair as a context unit |
| User makes a decision | Detects decision patterns → tags as `decision` type |
| User closes chat | Chat fully synced to Loom context store |
| Next `@loom` prompt | CLI retrieves synced context automatically |

## Bidirectional Loop (Later Phase)

```
Browser: You design architecture
  → Extension syncs to Loom
    → @loom <prompt> in CLI retrieves context
      → AI responds with implementation
        → Response saved as new context
          → Extension can show agent activity
```

## Extension-Build Order

1. Extension connects to Loom context server (authenticates)
2. Click-to-link flow (one-tap project linking)
3. Auto-sync chat messages as context units
4. `@loom` command retrieves synced context
5. *Later:* Agent activity visible back in browser
