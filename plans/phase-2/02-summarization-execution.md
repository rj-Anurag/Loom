---
title: "Phase 2.2 — Hierarchical Summarization (Execution Plan)"
description: "Periodic hierarchical summarization worker: groups unsummarized units, generates LLM summaries, writes as summary-type units with supersedes edges, and boosts summary units in retrieval ranking."
status: completed
dependencies: ["phase-1/07-trust-tier.md", "phase-1/03-context-service-read.md", "phase-2/01-full-coordination-execution.md"]
---

# Hierarchical Summarization — Execution Plan

## Prerequisites

| # | Task | Check |
|---|---|---|
| P0 | Redis running (needed for project-level locks) | `redis-cli ping` → PONG |
| P1 | PostgreSQL running (needed for integration tests) | `pg_isready` |
| P2 | `groq` Python package installed (`pip install groq`) | `python -c "import groq"` |

---

## Subtask Index

| ID | Name | Est. Time | Depends On |
|---|---|---|---|
| A1 | Add LLMProvider protocol + StubLLMProvider + GroqLLMProvider in providers.py | 30 min | — |
| A2 | Add summarization settings in config.py | 10 min | — |
| B1 | Implement grouping strategy (grouping.py) | 30 min | A2 |
| B2 | Implement summarizer worker (summarizer.py) | 45 min | A1, A2, B1 |
| C1 | Add summary score boost in _compute_score + _compute_score_sql | 15 min | — |
| D1 | Create run-summarizer.sh entrypoint script | 10 min | B2 |
| E1 | Write grouping unit tests | 20 min | B1 |
| E2 | Write summarizer integration tests | 30 min | B2, C1 |

**Total estimated time: ~3 hours**

---

## Design Decisions (per Architect Review)

| # | Decision | Detail |
|---|---|---|
| 1 | **LLM Provider** | `LLMProvider` protocol (like `EmbeddingProvider`) with `StubLLMProvider` (tests) and `GroqLLMProvider` (production) |
| 2 | **Worker scheduling** | Time-based asyncio loop (matching embedding worker pattern) with unsummarized-count threshold check before each cycle |
| 3 | **Summary writes** | MUST use `write_context` service — never direct DB writes. Summarizer gets its own agent identity per project |
| 4 | **Event type** | Do NOT add `summarization` to EventType. Summary writes through `write_context` naturally produce write events with `type: "summary"` payload |
| 5 | **Score boost** | Flat +0.15 bonus in `_compute_score()` (not 1.5x multiplier — avoids noise amplification) |
| 6 | **Idempotency** | Deterministic `client_uuid` = `uuid.uuid5(SUMMARY_NS, sorted_original_unit_ids)` to prevent duplicate summaries for same group |
| 7 | **Concurrency prevention** | Redis project-level lock (`summarize:{project_id}`) during cycles |
| 8 | **Graceful degradation** | On LLM failure, skip group, log warning, retry next cycle |
| 9 | **New settings** | `summarization_window_minutes=10`, `summarization_max_units_per_group=50`, `summarization_min_units=5` |
| 10 | **Trust tier inheritance** | Summary inherits highest trust tier from source units |

---

## A1 — LLM Provider Protocol + Implementations

### Files
- **MODIFY** `loom/services/retrieval/providers.py` — add `LLMProvider` protocol, `StubLLMProvider`, `GroqLLMProvider`, `from_llm_config()` factory

### LLMProvider Protocol

```python
@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM summarization providers.

    Every provider must accept a list of context-unit dicts and return
    a condensed summary string preserving key decisions and state.
    """

    async def summarize(self, context_units: list[dict]) -> str:
        """Generate a summary of the given context units.

        Parameters
        ----------
        context_units : list[dict]
            Each dict has at least ``id``, ``content``, ``type``,
            ``trust_tier``, ``created_at``, and ``agent_id`` keys.

        Returns
        -------
        str
            The condensed summary text.
        """
        ...
```

### StubLLMProvider

```python
class StubLLMProvider:
    """Deterministic stub summarizer for tests.

    Returns a concatenation of the unit contents prefixed with
    a header, truncated at 1000 chars.  Always available — no
    external dependencies.
    """

    async def summarize(self, context_units: list[dict]) -> str:
        if not context_units:
            return ""
        header = f"Stub summary of {len(context_units)} units:\n"
        body = "; ".join(u.get("content", "")[:200] for u in context_units)
        return (header + body)[:1000]
```

### GroqLLMProvider

```python
class GroqLLMProvider:
    """LLM provider backed by the Groq API.

    Requires the ``groq`` package and ``GROQ_API_KEY`` environment
    variable.  Uses ``mixtral-8x7b-32768`` by default for fast
    summarization with large context windows.
    """

    _SUMMARY_PROMPT = (
        "You are a technical summarizer. Condense the following "
        "context units into a concise summary preserving key "
        "decisions, findings, and state. Omit low-signal details.\n\n"
        "# Context Units\n\n{units_text}"
    )

    MAX_INPUT_CHARS = 30000

    def __init__(
        self,
        model: str = "mixtral-8x7b-32768",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key

    async def summarize(self, context_units: list[dict]) -> str:
        if not context_units:
            return ""
        units_text = self._format_units(context_units)
        prompt = self._SUMMARY_PROMPT.format(units_text=units_text)

        import groq as groq_client

        client = groq_client.AsyncGroq(api_key=self._api_key)
        resp = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt[:self.MAX_INPUT_CHARS]}],
            temperature=0.3,
            max_tokens=1024,
        )
        return resp.choices[0].message.content or ""

    def _format_units(self, units: list[dict]) -> str:
        lines = []
        for i, u in enumerate(units, 1):
            lines.append(
                f"--- Unit {i} [{u.get('type', 'unknown')}] "
                f"(tier={u.get('trust_tier', 'agent')}) ---\n"
                f"{u.get('content', '')}"
            )
        return "\n\n".join(lines)
```

### Factory

```python
def from_llm_config() -> LLMProvider:
    """Build an LLM provider based on ``settings.summarization_provider``.

    ``"stub"`` (default) → :class:`StubLLMProvider`
    ``"groq"``           → :class:`GroqLLMProvider`
    """
    provider_name = settings.summarization_provider.lower()
    if provider_name == "groq":
        return GroqLLMProvider(api_key=settings.groq_api_key or None)
    return StubLLMProvider()
```

### Acceptance Criteria
- [ ] `LLMProvider` protocol defines `async def summarize(units: list[dict]) -> str`
- [ ] `StubLLMProvider` returns deterministic concatenation, no external deps
- [ ] `StubLLMProvider.summarize([])` returns empty string
- [ ] `GroqLLMProvider` sends prompt with formatted units to Groq API
- [ ] `GroqLLMProvider` respects `MAX_INPUT_CHARS` truncation
- [ ] `from_llm_config()` returns `StubLLMProvider` when `summarization_provider="stub"`
- [ ] `from_llm_config()` returns `GroqLLMProvider` when `summarization_provider="groq"`
- [ ] `GroqLLMProvider` is importable even when `groq` package is not installed (lazy import inside method)

---

## A2 — New Settings

### Files
- **MODIFY** `loom/config.py` — add summarization settings

### Changes

Add to `Settings` class:

```python
summarization_window_minutes: int = 10
"""Time window in minutes for grouping unsummarized units."""

summarization_max_units_per_group: int = 50
"""Maximum number of units per summarization group (oldest first)."""

summarization_min_units: int = 5
"""Minimum number of units required to trigger summarization of a group."""

summarization_provider: str = "stub"
"""LLM provider for summarization: ``"stub"`` or ``"groq"``."""

summarization_interval_minutes: int = 15
"""How often the summarization worker checks for work (already exists, keep)."""
```

### Acceptance Criteria
- [ ] All five settings have sensible defaults and are configurable via env vars
- [ ] `settings.summarization_window_minutes` defaults to 10
- [ ] `settings.summarization_max_units_per_group` defaults to 50
- [ ] `settings.summarization_min_units` defaults to 5
- [ ] `settings.summarization_provider` defaults to `"stub"`
- [ ] `settings.summarization_interval_minutes` already exists and remains at 15
- [ ] Settable via `.env`: `SUMMARIZATION_WINDOW_MINUTES`, `SUMMARIZATION_MAX_UNITS_PER_GROUP`, etc.

---

## B1 — Grouping Strategy

### Files
- **CREATE** `loom/services/retrieval/grouping.py`

### Design

The grouping module provides deterministic time-window grouping of unsummarized context units. "Unsummarized" means a unit has **no incoming `supersedes` edge** — no summary exists that supersedes it.

```
Algorithm:
1. SELECT all units for project WHERE
   id NOT IN (SELECT parent_id FROM context_edges WHERE relation = 'supersedes')
   ORDER BY created_at ASC
2. Assign each unit to a time window: floor(created_at / window_minutes) * window_minutes
3. Group units by time window
4. Skip groups with < min_units members
5. Truncate groups to max_units_per_group (take oldest)
6. Sort each group's unit IDs to produce a deterministic sorted_ids_string
```

### Interface

```python
from dataclasses import dataclass

SUMMARY_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "loom-summarization")
"""Namespace for deterministic summary client_uuid generation."""


@dataclass
class SummarizationGroup:
    """A group of unsummarized context units to be summarized together."""

    window_start: datetime          # Aligned time window boundary
    unit_ids: list[uuid.UUID]       # Sorted oldest-first
    contents: list[str]             # Corresponding content texts
    types: list[str]                # Corresponding unit types
    trust_tiers: list[str]          # Corresponding trust tiers
    agent_ids: list[uuid.UUID]      # Corresponding agent IDs
    created_ats: list[datetime]     # Corresponding timestamps
    highest_trust_tier: str         # Max trust tier from source units
    sorted_ids_string: str          # Sorted, comma-separated UUIDs for idempotency

    @property
    def summary_client_uuid(self) -> uuid.UUID:
        """Deterministic UUID for idempotent summary writes."""
        return uuid.uuid5(SUMMARY_NS, self.sorted_ids_string)


async def find_unsummarized_groups(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    window_minutes: int = 10,
    max_units_per_group: int = 50,
    min_units: int = 5,
) -> list[SummarizationGroup]:
    """Find and group unsummarized context units for a project.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    window_minutes : int
        Size of each time window in minutes.
    max_units_per_group : int
        Maximum units per group (oldest first).
    min_units : int
        Minimum units required to form a group.

    Returns
    -------
    list[SummarizationGroup]
        Groups ordered by window_start ascending (oldest first).
    """
    ...


async def count_unsummarized(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> int:
    """Return the count of unsummarized units for a project.

    Used by the worker to decide whether to run a summarization cycle.
    """
    ...
```

### SQL for `find_unsummarized_groups`

```sql
SELECT u.id, u.content, u.type, u.trust_tier, u.agent_id, u.created_at
FROM context_units u
WHERE u.project_id = :project_id
  AND u.id NOT IN (
    SELECT e.parent_id
    FROM context_edges e
    WHERE e.relation = 'supersedes'
  )
ORDER BY u.created_at ASC
```

### Trust Tier Hierarchy (for `highest_trust_tier`)

```python
_TRUST_TIER_ORDER = {"user": 3, "agent": 2, "external_tool": 1}
# Summary inherits the highest tier present among source units.
# E.g., if any source is "user", summary is "user".
```

### Acceptance Criteria
- [ ] `find_unsummarized_groups` returns units with no incoming `supersedes` edge
- [ ] Units are grouped into aligned `window_minutes` time windows
- [ ] Groups with fewer than `min_units` are omitted
- [ ] Groups are truncated to `max_units_per_group` (oldest preserved)
- [ ] Groups returned in chronological order (oldest window first)
- [ ] `summarization_client_uuid` is deterministic: same units → same UUID
- [ ] `highhest_trust_tier` is correctly computed per group
- [ ] `count_unsummarized` returns accurate count
- [ ] Units that were previously summarized (have incoming `supersedes`) are excluded
- [ ] Works with empty result set → returns `[]`

---

## B2 — Summarizer Worker

### Files
- **CREATE** `loom/services/retrieval/summarizer.py`

### Design

The summarizer worker runs in an asyncio loop on a timer. Each cycle:

1. Acquire Redis project lock (`summarize:{project_id}`) — skip if locked (another worker beat us)
2. Get/create summarizer agent identity for the project
3. Check `count_unsummarized` — skip if below threshold
4. `find_unsummarized_groups(...)` with settings from config
5. For each group:
   a. Check idempotency: does a summary with this `client_uuid` already exist?
   b. Call `LLMProvider.summarize(group.to_dicts())`
   c. Call `write_context(session, project_id, summarizer_agent_id, client_uuid=group.summary_client_uuid, type_="summary", content=summary_text, version=max_version+1, parent_ids=group.unit_ids, parent_relations=["supersedes"] * len(group))` — this creates the summary unit with `supersedes` edges
6. Release Redis lock
7. Sleep for `summarization_interval_minutes`

### Loop Interface

```python
"""Async summarization worker — periodically summarizes unsummarized context units.

Run as a standalone process::

    python -m loom.services.retrieval.summarizer

Or via the shell script::

    scripts/run-summarizer.sh
"""

SUMMARY_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "loom-summarization")

_shutdown: bool = False


async def _ensure_summarizer_agent(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> uuid.UUID:
    """Get or create the summarizer agent identity for a project.

    Returns the agent UUID.  The summarizer uses a well-known
    ``credentials_ref`` value of ``"__summarizer__"`` to identify
    itself across restarts.
    """
    ...


async def run_summarization_cycle(
    session: AsyncSession,
    project_id: uuid.UUID,
    redis: redis_async.Redis,
    llm_provider: LLMProvider | None = None,
    window_minutes: int | None = None,
    max_units_per_group: int | None = None,
    min_units: int | None = None,
) -> dict:
    """Run one summarization cycle for a single project.

    Returns a result dict with keys:
    - ``groups_found``: int
    - ``groups_summarized``: int
    - ``groups_skipped``: int
    - ``errors``: list[str]
    """
    # 1. Acquire Redis project lock
    # 2. Get summarizer agent
    # 3. Find unsummarized groups
    # 4. For each group: summarize → write_context
    # 5. Release lock
    # 6. Return result summary
    ...


async def run_summarization_loop() -> None:
    """Main asyncio entry point for the summarization worker.

    Startup:
        1. Register SIGTERM handler.
        2. Create DB engine + session factory.
        3. Create LLM provider from config.
        4. Connect to Redis.
        5. Enter the periodic loop.

    Loop:
        1. Discover all projects (SELECT DISTINCT project_id FROM projects).
        2. For each project, call ``run_summarization_cycle``.
        3. Sleep for ``settings.summarization_interval_minutes``.
        4. Continue until shutdown flag is set.
    """
    ...


async def main() -> None:
    """Entry point — sets up logging and runs the loop."""
    ...
```

### Lock Key Format

```
summarize:{project_id}
```

### Idempotency Check

Before writing a summary, check if a context unit with `client_uuid = group.summary_client_uuid` already exists. The `client_uuid` UNIQUE constraint in the DB handles this at the DB level, but we also check early to avoid unnecessary LLM calls.

```python
existing = await session.execute(
    select(ContextUnit).where(
        ContextUnit.client_uuid == group.summary_client_uuid
    )
)
if existing.scalar_one_or_none():
    logger.info("Summary already exists for group %s — skipping", group.sorted_ids_string)
    continue
```

### Redis Lock Code

```python
lock_key = f"summarize:{project_id}"
lock_acquired = await redis.set(lock_key, "1", nx=True, ex=300)  # 5 min TTL
if not lock_acquired:
    logger.info("Summarization lock held by another worker — skipping project %s", project_id)
    return {"groups_found": 0, "groups_summarized": 0, "groups_skipped": 0, "errors": []}

try:
    # ... do the work ...
finally:
    await redis.delete(lock_key)
```

### Version Calculation for Summary Writes

The summary unit's version should be `max(parent.version) + 1` to pass the version-conflict check in `write_context`. Since the summarizer reads the parent units just before writing, this is safe.

### Acceptance Criteria
- [ ] `run_summarization_cycle` acquires Redis lock before processing
- [ ] If lock is held by another worker, cycle skips gracefully
- [ ] `run_summarization_cycle` creates/looks up summarizer agent per project
- [ ] Summarizer agent uses `credentials_ref="__summarizer__"` convention
- [ ] Each group produces exactly one summary write via `write_context`
- [ ] Summary write creates `summary`-type unit with `supersedes` edges to originals
- [ ] Idempotency: same group never produces duplicate summaries (client_uuid unique)
- [ ] Highest trust tier from source units is inherited by the summary
- [ ] LLM failure for a group is logged, group skipped, cycle continues
- [ ] Redis lock is released in `finally` block (always released)
- [ ] `main()` handles SIGTERM for graceful shutdown
- [ ] `main()` processes all projects in each cycle
- [ ] Cycle sleeps `summarization_interval_minutes` between iterations

---

## C1 — Score Boost for Summary Units

### Files
- **MODIFY** `loom/services/context/service.py` — add `+0.15` bonus in `_compute_score` and `_compute_score_sql`

### Changes to `_compute_score` (line 454)

Add a `unit_type` parameter and apply a +0.15 bonus when the type is `"summary"`:

```python
def _compute_score(
    ts_rank: float | None,
    created_at: datetime,
    trust_tier: str,
    unit_type: str = "",  # NEW
) -> float:
    """..."""
    hours_since = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
    recency = 1.0 / (hours_since + 1.0)
    weight = TRUST_TIER_WEIGHTS.get(trust_tier, 0.4)

    score = 0.4 * (ts_rank or 0.0) + 0.3 * recency + 0.3 * weight
    # NEW: Flat +0.15 bonus for summary-type units
    if unit_type == "summary":
        score += 0.15
    return score
```

### Update callers

In `read_context` (line 557-562), pass `unit_type=row["type"]`:

```python
score = _compute_score(
    ts_rank=row["rank"],
    created_at=row["created_at"],
    trust_tier=row["trust_tier"],
    unit_type=row["type"],  # NEW
)
```

### Changes to `_compute_score_sql` (line 620)

Add `+ CASE WHEN u.type = 'summary' THEN 0.15 ELSE 0 END`:

```python
def _compute_score_sql() -> str:
    return (
        "(0.4 * COALESCE(ts_rank(...), 0)"
        " + 0.3 * (1.0 / (EXTRACT(EPOCH FROM (now() - u.created_at)) / 3600.0 + 1.0))"
        " + 0.3 * CASE u.trust_tier"
        "     WHEN 'user' THEN 1.0"
        "     WHEN 'agent' THEN 0.7"
        "     ELSE 0.4"
        "   END"
        " + CASE WHEN u.type = 'summary' THEN 0.15 ELSE 0.0 END)"  # NEW
    )
```

### Acceptance Criteria
- [ ] Summary units get +0.15 score bonus in Python `_compute_score`
- [ ] Summary units get +0.15 score bonus in SQL `_compute_score_sql`
- [ ] Non-summary units are unaffected (0.0 bonus)
- [ ] Existing `read_context` callers pass `unit_type` correctly
- [ ] All existing tests continue to pass (backward compatible — `unit_type` defaults to `""`)

---

## D1 — Script Runner

### Files
- **CREATE** `scripts/run-summarizer.sh`

### Content

```bash
#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Run the Loom async summarization worker.
#
# Usage:  scripts/run-summarizer.sh
#
# The worker runs on a timer, grouping unsummarized context units, generating
# LLM summaries, and writing them as summary-type context units with supersedes
# edges.  Run exactly one instance (project-level Redis lock prevents overlap).
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate virtual environment (respect LOOM_VENV if set)
VENV="${LOOM_VENV:-$PROJECT_ROOT/.venv}"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

cd "$PROJECT_ROOT"

echo "==> Starting Loom summarization worker (provider: ${LOOM_SUMMARIZATION_PROVIDER:-stub})"
python -m loom.services.retrieval.summarizer
```

### Acceptance Criteria
- [ ] Script activates virtual environment
- [ ] Script runs `python -m loom.services.retrieval.summarizer`
- [ ] Respects `LOOM_VENV` override
- [ ] Follows same pattern as `run-embedding-worker.sh`

---

## E1 — Grouping Unit Tests

### Files
- **CREATE** `tests/unit/test_grouping.py`

### Test Scenarios

```python
"""Unit tests for summarization grouping strategy — no Redis needed."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio

class TestFindUnsummarizedGroups:
    """Tests for find_unsummarized_groups in isolation."""

    async def test_empty_project_returns_empty_list(self):
        """No units → empty list."""
        ...

    async def test_all_units_unsummarized_returns_groups(self):
        """Fresh project with units in one window → one group."""
        ...

    async def test_units_with_supersedes_edge_excluded(self):
        """Units that already have a summary are excluded."""
        ...

    async def test_time_window_partitioning(self):
        """Units in different time windows form separate groups."""
        ...

    async def test_min_units_threshold_skips_small_groups(self):
        """Groups below min_units are omitted."""
        ...

    async def test_max_units_per_group_truncation(self):
        """Groups exceeding max_units_per_group are truncated (oldest preserved)."""
        ...

    async def test_deterministic_client_uuid(self):
        """Same units produce the same summary_client_uuid."""
        ...

    async def test_highest_trust_tier_inherited(self):
        """highest_trust_tier reflects the max trust tier in the group."""
        ...


class TestCountUnsummarized:
    """Tests for count_unsummarized."""

    async def test_counts_only_unsummarized(self):
        """Units with supersedes edges are not counted."""
        ...
```

### Acceptance Criteria
- [ ] All grouping logic is tested without needing Redis
- [ ] Time window partitioning is correctly tested with synthetic timestamps
- [ ] Idempotency UUID is deterministic
- [ ] Trust tier inheritance is verified
- [ ] Edge cases: empty project, single unit below threshold, etc.

---

## E2 — Summarizer Integration Tests

### Files
- **CREATE** `tests/integration/test_summarizer.py`

### Fixtures

Same fixture pattern as `test_embedding_pipeline.py`:
- `redis_client` — Redis fixture with `flushdb` + skip if unavailable
- `client` — ASGI transport client
- `db_session` — async session factory
- `test_project` — minimal project
- `test_agent` — local agent
- `auth_headers` — bearer token header

### Test Scenarios

```python
"""Integration tests for the summarizer worker — requires Redis + Postgres."""


class TestSummarizerCycle:
    """Tests for run_summarization_cycle."""

    async def test_cycle_creates_summary_unit(
        self, redis_client, db_session, test_project, test_agent,
    ):
        """Successful cycle creates a summary-type context unit."""
        # Arrange: insert some unsummarized units
        # Act: run_summarization_cycle(test_project.id)
        # Assert: a context_unit with type='summary' exists
        ...

    async def test_summary_has_supersedes_edges(
        self, redis_client, db_session, test_project, test_agent,
    ):
        """Summary unit has supersedes edges to all source units."""
        ...

    async def test_idempotency_skips_duplicate_summary(
        self, redis_client, db_session, test_project, test_agent,
    ):
        """Running the same cycle twice does not create duplicate summaries."""
        ...

    async def test_lock_prevents_concurrent_cycles(
        self, redis_client, db_session, test_project,
    ):
        """When lock is held, cycle returns without processing."""
        ...

    async def test_llm_failure_skips_group(
        self, redis_client, db_session, test_project, test_agent,
    ):
        """When LLM provider raises, group is skipped, cycle continues."""
        ...


class TestSummarizerLoop:
    """Tests for the full loop (timeout-based)."""

    async def test_loop_processes_all_projects(
        self, redis_client, db_session,
    ):
        """Loop discovers all projects and runs a cycle per project."""
        ...


class TestSummarizerAgent:
    """Tests for summarizer agent identity."""

    async def test_agent_created_if_not_exists(
        self, db_session, test_project,
    ):
        """_ensure_summarizer_agent creates a new agent when none exists."""
        ...

    async def test_agent_reused_if_exists(
        self, db_session, test_project,
    ):
        """_ensure_summarizer_agent returns existing agent."""
        ...

    async def test_agent_has_cloud_kind_and_wellknown_ref(
        self, db_session, test_project,
    ):
        """Agent has kind='cloud' and credentials_ref='__summarizer__'."""
        ...


class TestScoreBoost:
    """Tests for the +0.15 summary score bonus."""

    async def test_summary_gets_boost(
        self, client, test_project, auth_headers, db_session, test_agent,
    ):
        """Summary units appear ranked higher than equivalently-scored non-summaries."""
        # Arrange: create one summary and one non-summary with similar content
        # Act: read_context with a matching query
        # Assert: the summary has a higher relevance_score than the raw unit
        ...
```

### Acceptance Criteria
- [ ] Summarization cycle produces a summary unit in the DB
- [ ] `supersedes` edges are created between summary and source units
- [ ] Idempotency prevents duplicate summaries
- [ ] Redis lock prevents concurrent cycles
- [ ] LLM failure logs warning and continues to next group
- [ ] Summarizer agent is auto-created with correct properties
- [ ] Score boost integration test confirms summaries rank higher
- [ ] All existing tests pass (no regressions)

---

## Execution Order DAG

```
A2 (Settings) ──────▶ B1 (grouping.py) ──▶ E1 (Grouping tests)
                                                          │
                                                          ▼
A1 (LLM provider) ───▶ B2 (summarizer.py) ──▶ D1 (summarizer.sh)
                          │                        │
                          ▼                        ▼
                     E2 (Summarizer tests)    C1 (Score boost)
                          │                        │
                          ▼                        ▼
                     E2 confirms full cycle   C1 confirmed by
                     with write_context       existing read tests
```

### Dependency Rationale

| Edge | Why |
|---|---|
| **A2 → B1** | Grouping uses `summarization_window_minutes` etc. from config |
| **A1 → B2** | Summarizer worker needs an LLM provider to call |
| **B1 → B2** | Summarizer worker imports `find_unsummarized_groups` |
| **B1 → E1** | Unit tests for grouping depend only on grouping module |
| **B2 → D1** | Shell script wraps the worker module |
| **B2 → E2** | Integration tests depend on the full worker |
| **B2, C1 → E2** | Integration tests verify both cycle + score boost |
| **C1** | Standalone — can be implemented in parallel with B1/B2 |

### Parallelism Opportunities

- **A1** and **A2** can be done in parallel (no dependencies between them)
- **C1** (score boost) can be done in parallel with **B1** and **B2** (no dependencies)
- **E1** (grouping tests) can start as soon as **B1** is done
- **E2** (summarizer tests) is the final integration gate

### Recommended Execution Order

```
Phase 1:  A1 + A2 (parallel) ──→ C1 (parallel)
Phase 2:  B1 (after A2) ──→ E1 (after B1)
Phase 3:  B2 (after A1 + A2 + B1)
Phase 4:  D1 (after B2)
Phase 5:  E2 (after B2 + C1)  ← final gate
```
