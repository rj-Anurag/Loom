"""Task CRUD and state machine for the Coordination Service.

Provides create, assign, start, complete, and fail operations with
valid state transitions enforced.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Task

# ── Valid transitions ─────────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"assigned", "failed"},
    "assigned": {"in_progress", "failed"},
    "in_progress": {"completed", "failed"},
    "completed": set(),  # terminal
    "failed": set(),  # terminal
}


def _validate_transition(current: str, target: str) -> None:
    """Raise ``ValueError`` if the transition is not allowed."""
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"INVALID_TRANSITION: {current} -> {target}"
        )


# ── Task CRUD ─────────────────────────────────────────────────────────────────


async def create_task(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    *,
    description: str | None = None,
    assigned_to: uuid.UUID | None = None,
) -> Task:
    """Create a new task.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    title : str
        Task title.
    description : str | None
        Optional task description.
    assigned_to : uuid.UUID | None
        Optional agent to assign immediately.

    Returns
    -------
    Task
        The newly created task.

    Raises
    ------
    ValueError
        With ``AGENT_NOT_FOUND`` if the assigned agent doesn't exist.
    """
    if assigned_to is not None:
        agent = await session.get(Agent, assigned_to)
        if agent is None or agent.project_id != project_id:
            raise ValueError("AGENT_NOT_FOUND")

    task = Task(
        project_id=project_id,
        title=title,
        description=description,
        status="assigned" if assigned_to else "pending",
        assigned_to=assigned_to,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: str | None = None,
) -> list[Task]:
    """List tasks for a project, optionally filtered by status."""
    query = select(Task).where(Task.project_id == project_id)
    if status is not None:
        query = query.where(Task.status == status)
    query = query.order_by(Task.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> Task | None:
    """Get a single task by ID."""
    return await session.get(Task, task_id)


# ── State machine transitions ─────────────────────────────────────────────────


async def assign_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> Task:
    """Assign a pending task to an agent.

    Transitions: pending → assigned

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    task_id : uuid.UUID
        Task to assign.
    agent_id : uuid.UUID
        Agent to assign.

    Returns
    -------
    Task
        Updated task.

    Raises
    ------
    ValueError
        With ``TASK_NOT_FOUND``, ``AGENT_NOT_FOUND``, or ``INVALID_TRANSITION``.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError("TASK_NOT_FOUND")

    _validate_transition(task.status, "assigned")

    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != task.project_id:
        raise ValueError("AGENT_NOT_FOUND")

    task.assigned_to = agent_id
    task.status = "assigned"
    await session.commit()
    await session.refresh(task)
    return task


async def start_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    branch_id: uuid.UUID | None = None,
) -> Task:
    """Start work on a task, optionally linking a branch.

    Transitions: assigned → in_progress

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    task_id : uuid.UUID
        Task to start.
    branch_id : uuid.UUID | None
        Optional branch to associate with this task.

    Returns
    -------
    Task
        Updated task.

    Raises
    ------
    ValueError
        With ``TASK_NOT_FOUND`` or ``INVALID_TRANSITION``.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError("TASK_NOT_FOUND")

    _validate_transition(task.status, "in_progress")

    task.status = "in_progress"
    if branch_id is not None:
        from loom.models import Branch

        branch = await session.get(Branch, branch_id)
        if branch is None or branch.project_id != task.project_id:
            raise ValueError("BRANCH_NOT_FOUND")
        task.branch_id = branch_id
    await session.commit()
    await session.refresh(task)
    return task


async def complete_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> Task:
    """Mark a task as completed.

    Transitions: in_progress → completed

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    task_id : uuid.UUID
        Task to complete.

    Returns
    -------
    Task
        Updated task.

    Raises
    ------
    ValueError
        With ``TASK_NOT_FOUND`` or ``INVALID_TRANSITION``.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError("TASK_NOT_FOUND")

    _validate_transition(task.status, "completed")

    task.status = "completed"
    await session.commit()
    await session.refresh(task)
    return task


async def fail_task(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> Task:
    """Mark a task as failed.

    Transitions: any non-terminal state → failed

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    task_id : uuid.UUID
        Task to fail.

    Returns
    -------
    Task
        Updated task.

    Raises
    ------
    ValueError
        With ``TASK_NOT_FOUND`` or ``INVALID_TRANSITION`` (terminal).
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise ValueError("TASK_NOT_FOUND")

    if task.status in ("completed", "failed"):
        _validate_transition(task.status, "failed")  # will raise

    task.status = "failed"
    await session.commit()
    await session.refresh(task)
    return task
