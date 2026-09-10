"""Integration tests for Phase 2.1 — Task lifecycle via HTTP API.

Tests define the expected behaviour of REST endpoints that will exist at
``/v1/projects/{project_id}/tasks``:

    POST   /v1/projects/{project_id}/tasks                   → Create task (201)
    GET    /v1/projects/{project_id}/tasks                    → List tasks (200)
    GET    /v1/projects/{project_id}/tasks/{id}               → Get task (200 / 404)
    POST   /v1/projects/{project_id}/tasks/{id}/assign        → Assign task (200)
    POST   /v1/projects/{project_id}/tasks/{id}/start         → Start task (200)
    POST   /v1/projects/{project_id}/tasks/{id}/complete      → Complete task (200)
    POST   /v1/projects/{project_id}/tasks/{id}/fail          → Fail task (200)

Task state machine::

    pending ──► assigned ──► in_progress ──► completed
                    │                           │
                    └──► failed ◄────────────────┘
    (any state) ──────────────────► failed

All tests use existing fixtures from ``tests/conftest.py`` plus local
fixtures defined here.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    p = Project(name="Task Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def auth_headers(test_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_agent.id}"}


# ── Task create ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """POST tasks returns 201 with task data including id, title, status."""
    body = {
        "title": "Implement JWT authentication",
        "description": "Add JWT-based auth middleware to the API",
    }
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "id" in data
    assert data["title"] == "Implement JWT authentication"
    assert data["status"] == "pending"
    assert "created_at" in data
    assert "project_id" in data
    assert data["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_create_task_with_options(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Task can be created with optional description."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={
            "title": "High-priority task",
            "description": "This is urgent",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "This is urgent"
    assert data["status"] == "pending"


# ── Task list ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tasks(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET tasks returns project-scoped task list."""
    titles = ["Task Alpha", "Task Beta"]
    created_ids = []
    for title in titles:
        resp = await client.post(
            f"/v1/projects/{test_project.id}/tasks",
            json={"title": title},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    resp = await client.get(
        f"/v1/projects/{test_project.id}/tasks",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    returned_ids = [t["id"] for t in data]
    for cid in created_ids:
        assert cid in returned_ids, f"Task {cid} should be in the list"
    assert all(t["project_id"] == str(test_project.id) for t in data)


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """GET tasks?status=completed returns only completed tasks."""
    # Create a completed task and a pending task
    # (We need to go through the lifecycle for the completed one)
    task_resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Will complete"},
        headers=auth_headers,
    )
    assert task_resp.status_code == 201
    complete_id = task_resp.json()["id"]

    task_resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Will stay pending"},
        headers=auth_headers,
    )
    assert task_resp.status_code == 201
    pending_id = task_resp.json()["id"]

    # Complete the first task
    # Assign → start → complete
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{complete_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{complete_id}/start",
        json={},
        headers=auth_headers,
    )
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{complete_id}/complete",
        headers=auth_headers,
    )

    # Filter by completed
    resp = await client.get(
        f"/v1/projects/{test_project.id}/tasks?status=completed",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    tasks = resp.json()
    completed_ids = [t["id"] for t in tasks]
    assert complete_id in completed_ids
    assert pending_id not in completed_ids


# ── Task get (single) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_task(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET tasks/{id} returns 200 with the full task record."""
    create_resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Feature X", "description": "Implement feature X"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    resp = await client.get(
        f"/v1/projects/{test_project.id}/tasks/{task_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["title"] == "Feature X"
    assert data["description"] == "Implement feature X"


@pytest.mark.asyncio
async def test_get_nonexistent_task(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """GET tasks/{id} for a nonexistent id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(
        f"/v1/projects/{test_project.id}/tasks/{fake_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── Full lifecycle ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_lifecycle(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """A task can go through the full lifecycle: create → assign → start → complete."""
    # 1. Create task
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Lifecycle task"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    # 2. Assign
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Assign failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "assigned"
    assert data["assigned_to"] == str(test_agent.id)

    # 3. Start
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/start",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Start failed: {resp.text}"
    assert resp.json()["status"] == "in_progress"

    # 4. Complete
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/complete",
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Complete failed: {resp.text}"
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_start_task_with_branch(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """Starting a task can optionally create a branch for the task."""
    # Create task
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Branch-linked task"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    # Assign
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Start
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/start",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Start with branch failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "in_progress"


# ── Invalid transitions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_transition_complete_pending(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Completing a task that is still 'pending' (not assigned/started) returns 400."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Invalid transition test"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/complete",
        headers=auth_headers,
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_invalid_transition_start_completed(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """Starting a completed task returns 400."""
    # Full lifecycle to completion
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Already done"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/start",
        json={},
        headers=auth_headers,
    )
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/complete",
        headers=auth_headers,
    )

    # Try starting again
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/start",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"


# ── Assign to nonexistent agent ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_to_nonexistent_agent(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Assigning a task to a nonexistent agent returns 404."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "No-agent task"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ── Fail from any state ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_task_from_pending(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """A pending task can be failed."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Fail from pending"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/fail",
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Fail from pending failed: {resp.text}"
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_fail_task_from_assigned(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """An assigned task can be failed."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Fail from assigned"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )

    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/fail",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_fail_task_from_in_progress(
    client: AsyncClient,
    test_project: Project,
    test_agent: Agent,
    auth_headers: dict[str, str],
) -> None:
    """An in-progress task can be failed."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Fail from in_progress"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/assign",
        json={"agent_id": str(test_agent.id)},
        headers=auth_headers,
    )
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/start",
        json={},
        headers=auth_headers,
    )

    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/fail",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_fail_task_from_failed(
    client: AsyncClient,
    test_project: Project,
    auth_headers: dict[str, str],
) -> None:
    """Failing an already-failed task returns 400 (no-op not allowed)."""
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks",
        json={"title": "Double fail"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    # First fail
    await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/fail",
        headers=auth_headers,
    )

    # Second fail should fail
    resp = await client.post(
        f"/v1/projects/{test_project.id}/tasks/{task_id}/fail",
        headers=auth_headers,
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
