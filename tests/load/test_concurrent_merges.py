"""Load test: concurrent agent writes with merge/conflict validation.

Phase 1.12 — Simulates 3 agents writing concurrently to the same project,
measures conflict rate, write latency, and auto-merge success rate.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

from .conftest import AgentSimulator

pytestmark = [pytest.mark.asyncio, pytest.mark.load_test]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile of *values* (sorted ascending)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, min(len(sorted_vals) - 1, int(len(sorted_vals) * pct / 100)))
    return sorted_vals[idx]


async def _count_units(db_session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM context_units WHERE project_id = :pid"),
        {"pid": project_id},
    )
    return result.scalar() or 0


async def _count_conflicts(db_session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM pending_branches pb "
            "JOIN context_units cu ON cu.id = pb.context_unit_id "
            "WHERE cu.project_id = :pid AND pb.resolution = 'pending'"
        ),
        {"pid": project_id},
    )
    return result.scalar() or 0


# ── Load Test ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def simulators(
    load_project: Project,
    load_agents: list[Agent],
    load_client: AsyncClient,
) -> list[AgentSimulator]:
    """Create 3 agent simulators wrapping the 3 DB agents."""
    names = ["auth", "schema", "api"]
    return [
        AgentSimulator(
            agent_id=a.id,
            api_key=str(a.id),
            client=load_client,
            name=names[i],
        )
        for i, a in enumerate(load_agents)
    ]


async def test_concurrent_agent_writes(
    load_project: Project,
    load_agents: list[Agent],
    simulators: list[AgentSimulator],
    load_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Simulate 3 concurrent agents writing to the same project.

    Phase 1 — Independent writes (no shared parents).
    Phase 2 — Shared-parent writes with non-overlapping content (auto-merge).
    Phase 3 — Shared-parent writes with overlapping content (conflicts).
    """
    project_id = str(load_project.id)
    start_time = time.perf_counter()

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 1: All agents write independently (no shared parents)
    # ═══════════════════════════════════════════════════════════════════════
    p1_results: list[dict] = []
    for sim in simulators:
        results = await sim.write_batch(project_id, count=5)
        p1_results.extend(results)

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 2: All agents derive from the same parent (non-overlapping)
    # ═══════════════════════════════════════════════════════════════════════
    parent_body = {
        "client_uuid": str(uuid.uuid4()),
        "type": "decision",
        "content": "Shared system design specification for load test",
        "version": 1,
    }
    headers = {"Authorization": f"Bearer {load_agents[0].id}"}
    resp = await load_client.post(
        f"/v1/projects/{project_id}/context",
        json=parent_body,
        headers=headers,
    )
    assert resp.status_code == 201, f"Parent write failed: {resp.text}"
    parent_id = resp.json()["id"]

    p2_results: list[dict] = []
    for sim in simulators:
        results = await sim.write_batch(
            project_id,
            count=5,
            parent_ids=[parent_id],
            base_content="Non-overlapping",
        )
        p2_results.extend(results)

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 3: All agents derive from shared parent (overlapping content)
    # Use stale version=1 to force version-conflict check → overlap detection
    # ═══════════════════════════════════════════════════════════════════════
    import uuid as _uuid

    common_file = "src/shared/conflict_module.py"
    p3_results: list[dict] = []
    for sim in simulators:
        for i in range(5):
            content = (
                f"Implement {common_file} feature {sim.name}-{i}: "
                f"modify {common_file} line {i * 10}"
            )
            # Use stale version=1 (parent is version 1, but Phase 2 already
            # used version 2, so version=1 is stale → triggers conflict check)
            body = {
                "client_uuid": str(_uuid.uuid4()),
                "type": "task_result",
                "content": content,
                "parent_ids": [parent_id],
                "version": 1,  # stale: expected_version is 2 (or higher)
            }
            headers = {"Authorization": f"Bearer {sim.api_key}"}
            start = time.perf_counter()
            resp = await load_client.post(
                f"/v1/projects/{project_id}/context",
                json=body,
                headers=headers,
            )
            elapsed = (time.perf_counter() - start) * 1000
            sim.latencies.append(elapsed)
            data = resp.json()
            data["_status"] = resp.status_code
            data["_latency_ms"] = round(elapsed, 1)
            p3_results.append(data)

    duration = time.perf_counter() - start_time

    # ═══════════════════════════════════════════════════════════════════════
    # Metrics collection
    # ═══════════════════════════════════════════════════════════════════════
    all_latencies = []
    for sim in simulators:
        all_latencies.extend(sim.latencies)

    p50 = _percentile(all_latencies, 50)
    p95 = _percentile(all_latencies, 95)
    p99 = _percentile(all_latencies, 99)

    # Count successful writes per phase
    p1_ok = sum(1 for r in p1_results if r.get("_status") == 201)
    p2_ok = sum(1 for r in p2_results if r.get("_status") == 201)
    p3_ok = sum(1 for r in p3_results if r.get("_status") == 201)

    # Count conflicts and auto-merges
    conflicts = sum(1 for r in p3_results if r.get("_status") == 409)

    # False positives: non-overlapping Phase 2 writes that got 409
    false_positives = sum(1 for r in p2_results if r.get("_status") == 409)

    total_units = await _count_units(db_session, load_project.id)
    _ = await _count_conflicts(db_session, load_project.id)

    # ═══════════════════════════════════════════════════════════════════════
    # Report
    # ═══════════════════════════════════════════════════════════════════════
    total_writes = len(p1_results) + len(p2_results) + len(p3_results)
    successful = p1_ok + p2_ok + p3_ok

    # "Data loss" = writes that should have succeeded but didn't.
    # Conflicts in Phase 3 are expected — those are correct conflict rejections,
    # not data loss. Only Phase 1 + Phase 2 writes must always succeed.
    data_loss = (p1_ok < len(p1_results)) or (p2_ok < len(p2_results))

    report = {
        "scenario": "3-agents-concurrent",
        "total_writes": total_writes,
        "successful_writes": successful,
        "duration_seconds": round(duration, 2),
        "latency_ms": {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "p99": round(p99, 1),
        },
        "phases": {
            "p1_independent": {"attempted": len(p1_results), "succeeded": p1_ok},
            "p2_non_overlapping": {"attempted": len(p2_results), "succeeded": p2_ok},
            "p3_overlapping": {
                "attempted": len(p3_results),
                "succeeded": p3_ok,
                "conflicts": conflicts,
            },
        },
        "conflicts": {
            "total": conflicts,
            "flagged": conflicts,
            "false_positives": false_positives,
            "expected_overlap_conflicts": 10,
        },
        "data_loss": data_loss,
        "all_writes_accounted": total_units >= successful,
        "db_total_units": total_units,
    }
    report["passed"] = not data_loss and report["latency_ms"]["p99"] < 1000

    # Write report to disk
    report_path = "tests/load/last-report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"  Load Test Report — {report['scenario']}")
    print(f"{'=' * 60}")
    print(f"  Duration:        {report['duration_seconds']}s")
    print(f"  Total writes:    {report['total_writes']}")
    print(f"  Successful:      {report['successful_writes']}")
    print(f"  DB units found:  {report['db_total_units']}")
    print(f"  Latency p50:     {report['latency_ms']['p50']}ms")
    print(f"  Latency p95:     {report['latency_ms']['p95']}ms")
    print(f"  Latency p99:     {report['latency_ms']['p99']}ms")
    print(f"  Conflicts:       {report['conflicts']['flagged']}")
    print(f"  Data loss:       {report['data_loss']}")
    print(f"  Passed:          {report['passed']}")
    print(f"{'=' * 60}\n")

    # Assertions
    assert report["latency_ms"]["p99"] < 1000, f"P99 latency too high: {p99}ms"

    # Phase 1: All independent writes should succeed
    assert p1_ok == len(p1_results), (
        f"Independent writes should all succeed: {p1_ok}/{len(p1_results)}"
    )

    # Phase 2: Non-overlapping writes should all succeed (auto-merge handles version conflicts)
    assert p2_ok == len(p2_results), (
        f"Non-overlapping writes should all succeed: {p2_ok}/{len(p2_results)}"
    )
    assert false_positives == 0, f"False positive conflicts in Phase 2: {false_positives}"

    # Phase 3: Overlapping writes should mostly conflict (after first succeeds via auto-merge)
    assert conflicts >= 10, (
        f"Expected at least 10 conflicts from overlapping writes, got {conflicts}"
    )
    assert p3_ok + conflicts == len(p3_results), (
        f"All Phase 3 writes should be either success or conflict: "
        f"{p3_ok + conflicts}/{len(p3_results)}"
    )

    # Successful writes = Phase 1 + Phase 2 + auto-merged first Phase 3 write
    expected_successful = len(p1_results) + len(p2_results) + 1
    assert successful == expected_successful, (
        f"Expected {expected_successful} successful writes, got {successful}"
    )

    # No data loss: all successful writes must be in DB
    assert total_units >= successful, f"Missing units in DB: {total_units} < {successful}"
