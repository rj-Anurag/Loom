---
title: "Phase 2.2 — Hierarchical Summarization"
description: "Periodic summarization that creates summary-type Context Units with supersedes edges. Retrieval prefers summaries."
status: completed
dependencies: ["phase-1/07-trust-tier.md", "phase-1/03-context-service-read.md"]
---

# Hierarchical Summarization

## Description
As the context graph grows, loading all raw units becomes inefficient. Hierarchical summarization creates condensed summary units that capture essential information. Retrieval prefers these summaries, falling back to originals only when needed.

## How It Works
Raw units are grouped by time windows (e.g., 10 minutes) or by topic clustering. An LLM generates a concise summary of each group. The summary is written as a `summary`-type context unit with `supersedes` edges to all originals. Retrieval ranking gives summary units a score boost.

## Summarization Worker
Create `services/retrieval/summarizer.py`:

```python
async def run_summarization_cycle(project_id):
    groups = await find_unsummarized_groups(project_id)
    for group in groups:
        summary = await generate_summary(group)
        await write_summary_unit(project_id, summary, group)
```

### Grouping Strategy (v1)
Simple time-window grouping: group unsummarized units into windows of 10 minutes. Unsummarized units are those that have no `supersedes` edge pointing to them.

### LLM Summarization
Each group of units is formatted and sent to an LLM with a summarization prompt. The LLM returns a condensed summary preserving key decisions, findings, and state.

### Retrieval Preference
In the read path, summary units get a 1.5x score boost so they appear above the raw units they summarize.

## Scheduling
- Default: every 15 minutes
- Configurable via `SUMMARIZATION_INTERVAL_MINUTES` env var
- Also triggers when unsummarized unit count passes a threshold

## File Targets
- `services/retrieval/summarizer.py` — summarization logic
- `services/retrieval/grouping.py` — grouping strategies
- `scripts/run-summarizer.sh` — entrypoint script

## Acceptance Criteria
- [ ] Summarization creates summary-type context units
- [ ] Summary units have `supersedes` edges to originals
- [ ] Retrieval prefers summary units over raw units
- [ ] Originals remain queryable (never deleted)
- [ ] Handles groups of 1-50 units
- [ ] Idempotent — running twice doesn't duplicate summaries

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_summarization_creates_summaries(summarizer, sample_units):
    result = await summarizer.run_cycle(project_id="test")
    assert result.summary_count > 0

@pytest.mark.asyncio
async def test_summary_has_supersedes_edges(summarizer, sample_units, db):
    await summarizer.run_cycle(project_id="test")
    edges = await db.fetch("SELECT * FROM context_edges WHERE relation = 'supersedes'")
    assert len(edges) > 0
```

## Dependencies
- Phase 1.3 (read path — needs retrieval preference for summaries)
