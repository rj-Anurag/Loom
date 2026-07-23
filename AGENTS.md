# Loom — Agentic TDD Pipeline & Git Workflow

## Orchestration Loop

Each phase follows this pipeline:

1. **Architect Review** — Validate design against `loom-architecture.md`
2. **Planning** — Break into subtasks with acceptance criteria
3. **TDD (Write Tests)** — Write tests before implementation (Red)
4. **Implementation** — Implement to make tests pass (Green)
5. **Verify** — Run all tests; loop back to step 4 if any fail
6. **Code Review** — Review diff for correctness, architecture fit, security, style
7. **Security Scan** — Secrets, injection vectors, dependency audit
8. **Documentation** — Update CHANGELOG.md, plans, README if needed
9. **Git Commit** — Commit with proper message (all tests must pass first)
10. **Git Push** — Ask user permission before pushing to main

## Git Rules

- **Commit only after all tests pass** with zero errors/warnings.
- **Commit message format**: `type: description` (feat, fix, refactor, docs, etc.)
- **Ask user permission before pushing** to main. Do not push without explicit approval.
- Push directly to `main` (no branching strategy currently).
- Do not amend committed changes — create fresh commits.
