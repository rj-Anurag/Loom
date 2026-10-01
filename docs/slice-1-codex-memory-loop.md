# Slice 1: Codex Project-Memory Loop

## Goal

Deliver one reliable project-memory loop:

```text
Repository binding
  -> Codex reads relevant Loom context
  -> Codex performs and verifies work
  -> Codex writes a structured task result
  -> A later agent retrieves that result with provenance
```

Slice 1 remains inside the modular monolith. It does not add agent-session
tables, dashboard changes, advanced retrieval ranking, Claude/OpenCode
installation, or noisy terminal-log capture.

## Architecture

```text
Repository
  .loom/project.json ------------+
  AGENTS.md managed block -------+--> Codex
                                      |
                                      v
                              Loom MCP stdio server
                                      |
                                      v
                                  Loom HTTP API
                                      |
                                      v
                              Context service / PostgreSQL
```

The repository descriptor selects the project without containing credentials.
The MCP process reads the matching key from the protected user-level Loom
configuration. The MCP server injects `codex_cli` provenance and a process-level
session ID into writes.

## Required Changes

### Repository binding

- Store `schema_version`, `api_url`, `project_id`, and `project_name` in
  `.loom/project.json`.
- Resolve configuration in this order: `LOOM_*` environment variables, nearest
  repository descriptor, then the global active-project fallback.
- Keep credentials exclusively in `~/.loom/projects.json`.
- Make `loom init` and `loom switch` write the descriptor atomically.
- Make `loom config` show the source of the active selection.

### Codex installation

- Register `loom mcp` through `codex mcp add` with
  `LOOM_SOURCE_TYPE=codex_cli`.
- Inspect an existing registration and refuse to overwrite an incompatible one.
- Support `--with-instructions` for an opt-in, idempotent Loom block in
  `AGENTS.md`.
- Preserve everything outside `<!-- loom:start -->` and `<!-- loom:end -->`.
- Require a read before work and a durable, secret-free summary after verified
  work.

### Provenance and structured results

- Add `source_type`, `source_session_id`, and JSON `metadata` to context units.
- Backfill browser writes as `browser_chat` and other existing writes as
  `mcp_agent`.
- Store task name, files touched, test results, errors, blockers, next steps,
  and optional confidence in metadata while keeping `content` readable and
  searchable.
- Preserve provenance in the event log and projection rebuild path.

### API and MCP contracts

- Keep existing REST clients compatible by deriving omitted provenance.
- Return source, session, agent name, and metadata in read/history responses.
- Let the server compute versions when clients omit them.
- Add structured task-result and parent-link fields to MCP `write_context`.
- Generate session-aware MCP idempotency keys.
- Return concise citations with full context-unit IDs from MCP `read_context`.

## Acceptance

1. Bind two repositories to different Loom projects and verify each resolves its
   own project regardless of the global active project.
2. Retrieve browser-chat context from Codex through MCP.
3. Write a structured Codex task result linked to the context used.
4. Retrieve that result from a fresh agent session with complete provenance.
5. Confirm `loom context "<query>" --scope full --json` exposes both sources.
6. Pass `ruff check .`, `mypy loom`, `pytest -q`, and
   `node --test tests/extension/*.js`.

## Deferred

- Dedicated agent-session tables
- Dashboard session views
- Claude Code and OpenCode installers
- `list_recent_context` and `list_sources`
- Advanced source-aware retrieval ranking
