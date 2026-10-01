# Browser Ingestion Audit

Audit date: 2026-10-01

## Purpose

Verify the existing browser-ingestion path before scheduling more implementation.
This audit does not change browser-ingestion code and uses the hosted Loom services
by default.

## Status Legend

- `[x]` verified
- `[~]` in progress
- `[ ]` not yet verified
- `[!]` blocked or failed
- `[-]` not required

## Checklist

```text
Browser Ingestion Audit
|
+-- [x] 0. Security gate
|   +-- [x] frontend/.env.local is not tracked by Git
|   +-- [x] .env.local is covered by .gitignore
|   +-- [x] No tracked frontend environment file contains the local token
|   `-- [-] Rotation is unnecessary: the local OIDC token expired on 2026-09-13
|
+-- [~] 1. Hosted infrastructure
|   +-- [ ] Check Render /health
|   +-- [ ] Check Render /ready
|   +-- [ ] Confirm PostgreSQL and Redis readiness
|   `-- [ ] Confirm the extension targets the hosted API
|
+-- [ ] 2. Link workflow
|   +-- [ ] Authenticate through the extension
|   +-- [ ] Select an existing project
|   +-- [ ] Link a test conversation
|   `-- [ ] Confirm the API returns the linked chat
|
+-- [ ] 3. Capture workflow
|   +-- [ ] Capture currently rendered messages
|   +-- [ ] Load and capture older messages
|   +-- [ ] Capture a newly added message
|   +-- [ ] Confirm messages are not duplicated
|   `-- [ ] Confirm scroll position is restored
|
+-- [ ] 4. Reliability
|   +-- [ ] Verify failed writes enter the retry queue
|   +-- [ ] Verify queued writes eventually synchronize
|   +-- [ ] Confirm one chat's failure does not affect another
|   `-- [ ] Confirm popup pending status is accurate
|
+-- [ ] 5. Project memory
|   +-- [ ] Retrieve a distinctive phrase with loom context
|   +-- [ ] Retrieve the same message through MCP
|   +-- [ ] Confirm source URL and browser_chat provenance
|   `-- [ ] Confirm two chats remain independently traceable
|
+-- [ ] 6. Existing automated coverage
|   +-- [ ] Run extension tests
|   +-- [ ] Run chat-link API tests
|   +-- [ ] Run context history tests
|   `-- [ ] Record coverage gaps without changing code
|
`-- [ ] 7. Audit decision
    +-- [ ] PASS: close browser ingestion and move forward
    +-- [ ] PARTIAL: create a small browser UX hardening slice
    `-- [ ] FAIL: create a focused reliability repair slice
```

## Evidence

### Security gate

- `git ls-files '*env*'` lists only `.env.example`, `environment.yml`, and
  `frontend/next-env.d.ts`.
- `git check-ignore -v frontend/.env.local` resolves to the `.env.local` rule
  in the root `.gitignore`.
- The local Vercel OIDC token expired on 2026-09-13. The ignored local file is
  retained because it is generated development state, not a committed secret.

## Decision Rules

- **PASS:** linking, historical capture, new-message capture, retry, and
  retrieval work. Remaining management UI is backlog work.
- **PARTIAL:** the core flow works, but a narrow reliability or management
  improvement is needed.
- **FAIL:** messages are lost, incorrectly duplicated, assigned to the wrong
  project, or cannot be retrieved.

