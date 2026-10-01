# Loom Next Version Roadmap

## Execution Documents

- [Slice 1: Codex Project-Memory Loop](docs/slice-1-codex-memory-loop.md)

## Summary

The next version should move Loom from “browser chat capture” to “shared memory for every coding agent working on a project.”

The core product loop should be:

```text
Any chat or agent session writes context into Loom.
Any future agent reads Loom before starting.
Every useful result gets written back.
```

## Step-By-Step To-Dos

### 1. Define The Loom Project Memory Model

- Treat a Loom project as the single source of context for one codebase.
- Store all context under one `project_id`, regardless of source.
- Keep source provenance for every context unit:
  `browser_chat`, `codex_cli`, `claude_code`, `opencode`, `manual_cli`, `dashboard`, `mcp_agent`.
- Store metadata for each unit:
  source app, source URL/session ID, role, timestamp, agent name, task name, files touched, confidence/trust tier.
- Make sure multiple chats and multiple agent sessions can all attach to the same project.

### 2. Strengthen Browser Chat Ingestion

- Keep the current extension flow for Claude/ChatGPT linking.
- Add reliable historical backfill for older messages rendered in the browser.
- Add visible sync status:
  linked, scanning, syncing, synced, failed, retrying.
- Add support for multiple linked chats per project in the dashboard UI.
- Add per-chat controls:
  resync, unlink, view captured messages, copy source URL.
- Normalize captured messages into the same context format used by agents.

### 3. Add Agent Session Capture

- Implement session-level context writes from coding harnesses.
- For Codex, use MCP plus `AGENTS.md` protocol:
  before work, read context; after work, write durable result.
- For Claude Code, support `/loom` or project command integration where possible.
- For OpenCode and similar tools, install the equivalent instruction/config file.
- Capture useful agent outputs:
  task summary, decisions, changed files, blockers, test results, errors, next steps.
- Do not store full noisy terminal logs by default; store durable summaries and important artifacts.

### 4. Build The Loom CLI Developer Flow

- `loom init` should create/select a project and write `.env`.
- `loom install codex|claude|opencode|all` should install harness-specific context instructions.
- `loom context "<query>" --scope full` should retrieve project memory.
- `loom write "<summary>" --type task_result` should write new durable context.
- Add a clearer command for project status, for example:
  `loom status`
- Add a command to list linked chats/sessions:
  `loom links`
- Add a command to inspect recent project memory:
  `loom history`

### 5. Add MCP-First Agent Integration

- Keep `loom mcp` as the universal integration layer.
- Expose MCP tools:
  `read_context`, `write_context`, `list_recent_context`, `list_sources`.
- Make the MCP tool responses concise enough for agents to use directly.
- Add source citations so agents can say where context came from.
- Ensure every agent credential is scoped to only one authorized project.
- Document the exact Codex setup command:
  `codex mcp add loom ... -- loom mcp`.

### 6. Improve Retrieval Quality

- Separate context into categories:
  decisions, task results, chat messages, architecture notes, blockers, files, errors.
- Rank results by relevance, recency, trust tier, and source type.
- Add summarization for large histories.
- Preserve original messages even when summaries are generated.
- Make `--scope task`, `--scope onboarding`, and `--scope full` meaningfully different.
- Add fallback keyword search when embeddings are unavailable.

### 7. Upgrade Dashboard

- Show one project page with all context sources:
  browser chats, agent sessions, manual notes, MCP writes.
- Add filters:
  source, date, role, type, agent, linked chat.
- Show a timeline of project memory.
- Show “what changed recently” for agents.
- Add a source detail page for each linked chat/session.
- Keep the dark Vercel/shadcn-style UI consistent with the extension.

### 8. Add Agent Activity And Collaboration

- Track active agents per project.
- Show current agent status:
  idle, reading context, coding, testing, blocked, completed.
- Store task runs as first-class records.
- Support handoff between agents:
  one agent writes a result, another reads and continues.
- Add conflict visibility when multiple agents write related context.

### 9. Harden Auth, Security, And Data Boundaries

- Keep per-agent API keys.
- Prevent one project’s key from reading another project.
- Add production bootstrap protection.
- Do not log API keys or secrets.
- Add rate limits for extension and agent writes.
- Validate source URLs and reject unsafe schemes.
- Add a clear local/dev versus production config path.

### 10. Production Readiness

- Add complete setup docs:
  local development, extension install, Codex MCP, Claude Code, dashboard.
- Add one full end-to-end testing guide:
  browser chat → Loom → dashboard → CLI → Codex → write back.
- Add automated tests for:
  multi-chat linking, agent writes, MCP read/write, dashboard history, auth boundaries.
- Add Docker production compose config.
- Add health checks and migration scripts.
- Add changelog entries for every release.

## Upcoming Version Acceptance Criteria

- A user can link multiple Claude/ChatGPT chats to one Loom project.
- A user can open Codex CLI in that repo and retrieve the linked chat context.
- Codex can write a task result back into Loom.
- A later Claude Code/OpenCode/Codex session can read that result.
- The dashboard shows browser chats and agent sessions together.
- The CLI can prove the full loop works with:
  `loom context "<query>" --scope full`.
- No context source is silently dropped.
- Every stored context item has provenance.

## Assumptions

- Loom should remain a modular monolith for the next version.
- Browser extensions remain the primary way to ingest private web chat pages.
- MCP is the primary integration layer for coding agents.
- Full private API import from Claude/ChatGPT is not part of the next version unless official APIs make it possible.
- The next version should focus on local developer workflows before enterprise/team features.
