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
9. **Git Commit** — Git agent (`.opencode/agents/git.md`) handles focused atomic commits
10. **Git Push** — Git agent asks user permission before pushing to main

## Delegation

The Orchestrator delegates specialized work to agents in `.opencode/agents/`:
- `git.md` — commit & push workflow (runs at pipeline end)
- `tester.md` — test execution
- `reviewer.md` — code review
- `security.md` — security audit
- Any other agent in `.opencode/agents/`

## Git Rules

- **Commit only after all tests pass** with zero errors/warnings.
- **Commit message format**: `type: description` (feat, fix, refactor, docs, etc.)
- **Ask user permission before pushing** to main. Do not push without explicit approval.
- Push directly to `main` (no branching strategy currently).
- Do not amend committed changes — create fresh commits.
- **Create focused, atomic commits.** Each commit should contain only the files relevant to one logical change. For example, Phase 0 scaffold and Phase 1.1 DB schema should be two separate commits, not one. Similarly, within a phase, split unrelated concerns (e.g., Redis config vs. pgvector migrations) into separate commits.
