"""Task management REST router.

Provides endpoints for the full task lifecycle: create, assign, start,
complete, and fail, with valid state transitions enforced.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.models import Agent, Task
from loom.services.coordination import CoordinationService

router = APIRouter()


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> None:
    """Verify the agent belongs to the project. Raises 404 if not."""
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")


class CreateTaskRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/tasks."""

    title: str = Field(..., min_length=1, description="Task title.")
    description: str | None = Field(None, description="Optional task description.")
    assigned_to: uuid.UUID | None = Field(
        None, description="Optional agent UUID to assign immediately."
    )


class AssignTaskRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/tasks/{id}/assign."""

    agent_id: uuid.UUID = Field(..., description="Agent UUID to assign.")


class StartTaskRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/tasks/{id}/start."""

    branch_id: uuid.UUID | None = Field(None, description="Optional branch UUID to associate.")


class TaskResponse(BaseModel):
    """Standard task response."""

    id: str
    project_id: str
    title: str
    description: str | None = None
    status: str
    assigned_to: str | None = None
    branch_id: str | None = None
    created_at: str


@router.post(
    "/{project_id}/tasks",
    status_code=201,
    response_model=TaskResponse,
    responses={
        201: {"description": "Task created"},
        400: {"description": "Validation error"},
        401: {"description": "Unauthorized"},
        404: {"description": "Assigned agent not found"},
    },
)
async def create_task_endpoint(
    project_id: uuid.UUID,
    body: CreateTaskRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Create a new task."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    try:
        task = await svc.create_task(
            project_id=project_id,
            title=body.title,
            description=body.description,
            assigned_to=body.assigned_to,
        )
    except ValueError as exc:
        if str(exc) == "AGENT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")
        raise HTTPException(status_code=400, detail=str(exc))

    return _task_to_response(task)


@router.get(
    "/{project_id}/tasks",
    response_model=list[TaskResponse],
    responses={
        200: {"description": "List of tasks"},
        401: {"description": "Unauthorized"},
    },
)
async def list_tasks_endpoint(
    project_id: uuid.UUID,
    status: str | None = None,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> list[TaskResponse]:
    """List tasks for a project, optionally filtered by status."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    tasks = await svc.list_tasks(project_id, status=status)
    return [_task_to_response(t) for t in tasks]


@router.get(
    "/{project_id}/tasks/{task_id}",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task details"},
        401: {"description": "Unauthorized"},
        404: {"description": "Task not found"},
    },
)
async def get_task_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Get a single task by ID."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    task = await svc.get_task(task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return _task_to_response(task)


@router.post(
    "/{project_id}/tasks/{task_id}/assign",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task assigned"},
        400: {"description": "Invalid state transition"},
        401: {"description": "Unauthorized"},
        404: {"description": "Task or agent not found"},
    },
)
async def assign_task_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: AssignTaskRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Assign a task to an agent."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    existing_task = await svc.get_task(task_id)
    if existing_task is None or existing_task.project_id != project_id:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    try:
        task = await svc.assign_task(
            task_id=task_id,
            agent_id=body.agent_id,
        )
    except ValueError as exc:
        error = str(exc)
        if error == "TASK_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error)
        if error == "AGENT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)

    return _task_to_response(task)


@router.post(
    "/{project_id}/tasks/{task_id}/start",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task started"},
        400: {"description": "Invalid state transition"},
        401: {"description": "Unauthorized"},
        404: {"description": "Task not found"},
    },
)
async def start_task_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: StartTaskRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Start work on a task, optionally linking a branch."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    existing_task = await svc.get_task(task_id)
    if existing_task is None or existing_task.project_id != project_id:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    try:
        task = await svc.start_task(
            task_id=task_id,
            branch_id=body.branch_id,
        )
    except ValueError as exc:
        error = str(exc)
        if error in {"TASK_NOT_FOUND", "BRANCH_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)

    return _task_to_response(task)


@router.post(
    "/{project_id}/tasks/{task_id}/complete",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task completed"},
        400: {"description": "Invalid state transition"},
        401: {"description": "Unauthorized"},
        404: {"description": "Task not found"},
    },
)
async def complete_task_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Mark a task as completed."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    existing_task = await svc.get_task(task_id)
    if existing_task is None or existing_task.project_id != project_id:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    try:
        task = await svc.complete_task(task_id)
    except ValueError as exc:
        error = str(exc)
        if error == "TASK_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)

    return _task_to_response(task)


@router.post(
    "/{project_id}/tasks/{task_id}/fail",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task failed"},
        400: {"description": "Invalid state transition (task already in terminal state)"},
        401: {"description": "Unauthorized"},
        404: {"description": "Task not found"},
    },
)
async def fail_task_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """Mark a task as failed."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    existing_task = await svc.get_task(task_id)
    if existing_task is None or existing_task.project_id != project_id:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    try:
        task = await svc.fail_task(task_id)
    except ValueError as exc:
        error = str(exc)
        if error == "TASK_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)

    return _task_to_response(task)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        project_id=str(task.project_id),
        title=task.title,
        description=task.description,
        status=task.status,
        assigned_to=str(task.assigned_to) if task.assigned_to else None,
        branch_id=str(task.branch_id) if task.branch_id else None,
        created_at=task.created_at.isoformat() if task.created_at else "",
    )
