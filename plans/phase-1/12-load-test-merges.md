---
title: "Phase 1.12 — Load Test: Concurrent Merges"
description: "Simulate 3+ agents writing concurrently. Measure conflict rate, write latency, and auto-merge success rate."
status: pending
dependencies: ["phase-1/08-basic-coordination.md"]
---

# Load Test: Concurrent Merges

## Description
Build and run a load test that simulates multiple agents writing to the same project concurrently. This is a critical validation step: the architecture review specifically called out that the merge/conflict path is the riskiest part of the system, and load testing must happen before Phase 1 is declared complete.

## Test Scenario

Simulate 3 agents working on the same project simultaneously:

- **Agent A**: Writes decisions about authentication
- **Agent B**: Writes decisions about database schema
- **Agent C**: Writes decisions about API design

Each agent writes 20 context units, with some writes deriving from the same parent (simulating concurrent work on a shared spec).

## Success Criteria

| Metric | Target |
|---|---|
| Write latency (p50) | < 200ms |
| Write latency (p99) | < 500ms |
| Non-overlapping auto-merge rate | 100% |
| Conflict detection accuracy | 100% (all true conflicts flagged) |
| False positive conflict rate | < 1% |
| Zero data loss | All 60 writes accounted for |

## Implementation

Create `tests/load/test_concurrent_merges.py`:

```python
@pytest.mark.load_test
async def test_concurrent_agent_writes():
    """
    Simulates 3 concurrent agents writing to the same project.
    """
    project = await create_test_project()
    agents = [
        await create_test_agent(project.id, "auth"),
        await create_test_agent(project.id, "schema"),
        await create_test_agent(project.id, "api"),
    ]

    # Phase 1: All agents write independently (no shared parents)
    async with TaskGroup() as tg:
        for agent in agents:
            tg.create_task(agent.write_batch(5))

    # Phase 2: All agents write with shared parents (potential conflicts)
    parent = await write_spec(project.id, "Shared system design")
    async with TaskGroup() as tg:
        for agent in agents:
            tg.create_task(agent.write_batch(5, parent_ids=[parent.id]))

    # Phase 3: Measure and report
    report = generate_report(project.id, agents)
    assert report["total_writes"] == 30
    assert report["auto_merge_rate"] == 1.0
    assert report["false_conflict_rate"] < 0.01
    assert report["p99_latency_ms"] < 500
```

### Metrics Collection

The load test collects:
- **Write latency**: Time from request to 201 response (p50, p95, p99)
- **Conflict rate**: Number of conflicts / total writes
- **Auto-merge rate**: Non-overlapping conflicts resolved / total non-overlapping conflicts
- **False positive rate**: Conflicts flagged that were not actual overlaps
- **Data loss**: All written context units should be queryable after the test

### Reporting

Output a structured JSON report:

```json
{
    "scenario": "3-agents-concurrent",
    "total_writes": 60,
    "duration_seconds": 12.5,
    "latency_ms": { "p50": 145, "p95": 320, "p99": 480 },
    "conflicts": {
        "total": 8,
        "auto_merged": 6,
        "flagged": 2,
        "false_positives": 0
    },
    "data_loss": false,
    "all_writes_accounted": true,
    "passed": true
}
```

## File Targets
- `tests/load/__init__.py`
- `tests/load/test_concurrent_merges.py` — the load test
- `tests/load/conftest.py` — fixtures (agent simulators, project setup)
- `scripts/run-load-tests.sh` — entrypoint to run load tests

## Execution
```bash
# Run the load test
python -m pytest tests/load/test_concurrent_merges.py -v --slow

# Generate report
python -m tests.load.report --input results.json --output load-test-report.md
```

## Acceptance Criteria

- [ ] Load test runs and produces a structured report
- [ ] All 60 writes are accounted for (zero data loss)
- [ ] Non-overlapping writes achieve 100% auto-merge rate
- [ ] P99 write latency is under 500ms
- [ ] False positive conflict rate is under 1%
- [ ] Report is written to `tests/load/last-report.json`

## Dependencies
- Phase 1.8 (coordination with merge/conflict logic)
- All prior Phase 1 subtasks (full write/read path must work)
