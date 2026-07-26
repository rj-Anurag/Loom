# ADR-001: Multi-Agent Concurrent Demo Architecture

**Status:** Proposed  
**Phase:** 2.6  
**Date:** 2026-07-26

## Context

We need an end-to-end demonstration that 3 concurrent agents (local, cloud, browser) can work on the same Loom project simultaneously, using the existing branch/merge/conflict infrastructure. The demo must be re-runnable, complete in under 2 minutes, and demonstrate auto-merge of non-overlapping writes plus conflict detection of overlapping writes.

## Decisions

### 1. Agent Architecture: Base class + content stubs

**Decision:** Create a `DemoAgent` base class in `agents/demo/base.py` that all three demo agents inherit from. They reuse `LoomClient` from `agents/local/agent.py` rather than writing raw HTTP calls.

**Rationale:**
- The three agents differ only in content and `kind` metadata — a base class avoids triplication
- Using `LoomClient` demonstrates that the agent interface is uniform across runtime locations (the architectural point)
- Raw HTTP calls would miss this architectural demonstration and duplicate existing client logic

**Tradeoff:** A base class is a small abstraction justified by 3× reuse.

### 2. Content Strategy: Deterministic stubs, opt-in live LLM

**Decision:** Default to deterministic stub content. Add `--live` flag for optional LLM generation via Groq.

**Rationale:**
- Stubs guarantee repeatability (same branch structure every run)
- Stubs eliminate API key dependency (CI-friendly)
- Stubs keep demo under 2 minutes (no LLM latency)
- Stub content can be deliberately shaped to trigger specific scenarios (auto-merge, overlap)
- Live mode exists for more impressive walkthroughs but is opt-in

**Tradeoff:** Stubs are less "realistic" but the demo tests infrastructure, not LLM quality.

### 3. Concurrency Model: Single-process asyncio Tasks

**Decision:** The coordinator runs agents as concurrent `asyncio.Task` instances in a single process, not as separate OS subprocesses.

**Rationale:**
- Agents are I/O-bound (HTTP calls to the Loom API) — asyncio concurrency is sufficient
- Simpler result collection, timeout enforcement, and error handling
- Agents appear independent to the Loom server (separate agent IDs, separate API keys)
- Eliminates subprocess overhead and shell scripting fragility

**Tradeoff:** True process isolation would be more realistic but adds complexity without architectural benefit for this demonstration.

### 4. Visualization: CLI-first, extension overlay deferred

**Decision:** Implement CLI output with ANSI-colored progress. Defer the "Demo Mode" extension overlay to a follow-up phase.

**Rationale:**
- The backend behavior (concurrent writes, branch/merge, conflict flags) is the architectural deliverable
- The extension sidebar from Phase 2.5 already shows agent activity — verify it works without a special overlay
- Extension JS changes have a different release cadence than Python backend scripts
- CLI visualization with structured output satisfies the acceptance criteria

### 5. Project and Agent Lifecycle: Coordinator-managed

**Decision:** The coordinator creates the project, registers agents, writes the initial project spec, runs agents, queries results, and reports. Each run creates a fresh project for idempotency.

**Rationale:**
- Fresh project per run guarantees idempotency across runs
- Registration must persist agent records in the DB for auth to work
- Initial project spec serves as the shared parent for all three agents

## Consequences

### What becomes easier
- Deterministic, runnable demo suitable for CI and sales demos
- Clear tests with predictable outcomes
- Clean separation between demo code and production code
- Reusable `LoomClient` pattern across all agent types

### What becomes harder
- Must fix the agent registration stub before the demo works (blocker)
- Must carefully design stub content to trigger overlap (entangled with entity extraction patterns in `merge.py`)
- Live mode requires `GROQ_API_KEY` and may exceed 2-minute timeout

## Alternatives Considered

| Alternative | Rejected Because |
|---|---|
| Raw HTTP in agent scripts | Misses architectural demonstration; duplicates LoomClient code |
| Subprocess per agent | Adds pid management, IPC, timeout complexity without benefit |
| Extension overlay only | Backend behavior must be verified first; overlay is presentation layer |
| LLM-only demo | Flaky, slow, API-key-dependent, unpredictable merge outcomes |
| Bash-only runner | No structured result collection; no timeout; fragile error handling |

## Dependencies

- Fix `POST /projects/{project_id}/agents` endpoint (currently returns empty strings)
