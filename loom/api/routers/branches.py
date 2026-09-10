"""Branch management REST router.

Provides endpoints for git-style branch creation, listing, and merging
for concurrent context writes.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.models import Agent
from loom.services.coordination import CoordinationService

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> None:
    """Verify the agent belongs to the project. Raises 404 if not."""
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")


# ── Request / Response models ─────────────────────────────────────────────────


class CreateBranchRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/branches."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable branch name.")
    source_branch_id: uuid.UUID | None = Field(None, description="Optional source branch UUID.")
    task_id: uuid.UUID | None = Field(None, description="Optional task UUID to associate.")


class MergeBranchResponse(BaseModel):
    """Response from POST /v1/projects/{id}/branches/{id}/merge."""

    status: str
    merge_unit_id: str | None = None
    conflict_ids: list[str] = []


@router.post(
    "/{project_id}/branches",
    status_code=201,
    responses={
        201: {"description": "Branch created"},
        400: {"description": "Validation error"},
        401: {"description": "Unauthorized"},
        409: {"description": "Branch name already taken"},
    },
)
async def create_branch_endpoint(
    project_id: uuid.UUID,
    body: CreateBranchRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new branch for a project."""
    await _verify_project_access(session, project_id, auth.agent_id)
    from loom.services.retrieval.queue import get_redis

    redis = None
    try:
        redis = get_redis()
    except Exception:
        pass

    svc = CoordinationService(session, redis)
    try:
        branch = await svc.create_branch(
            project_id=project_id,
            name=body.name,
            agent_id=auth.agent_id,
            source_branch_id=body.source_branch_id,
            task_id=body.task_id,
        )
    except ValueError as exc:
        error_code = str(exc)
        if error_code == "BRANCH_NAME_TAKEN":
            raise HTTPException(status_code=409, detail=error_code)
        if error_code in {"AGENT_NOT_FOUND", "SOURCE_BRANCH_NOT_FOUND", "TASK_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=error_code)
        raise HTTPException(status_code=400, detail=error_code)

    return {
        "id": str(branch.id),
        "project_id": str(branch.project_id),
        "name": branch.name,
        "status": branch.status,
        "source_branch_id": str(branch.source_branch_id) if branch.source_branch_id else None,
        "created_by": str(branch.created_by),
        "task_id": str(branch.task_id) if branch.task_id else None,
        "created_at": branch.created_at.isoformat() if branch.created_at else None,
    }


@router.get(
    "/{project_id}/branches",
    responses={
        200: {"description": "List of branches"},
        401: {"description": "Unauthorized"},
    },
)
async def list_branches_endpoint(
    project_id: uuid.UUID,
    status: str | None = None,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List branches for a project, optionally filtered by status."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    try:
        branches = await svc.list_branches(project_id, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return [
        {
            "id": str(b.id),
            "project_id": str(b.project_id),
            "name": b.name,
            "status": b.status,
            "source_branch_id": str(b.source_branch_id) if b.source_branch_id else None,
            "created_by": str(b.created_by),
            "task_id": str(b.task_id) if b.task_id else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "merged_at": b.merged_at.isoformat() if b.merged_at else None,
        }
        for b in branches
    ]


@router.get(
    "/{project_id}/branches/{branch_id}",
    responses={
        200: {"description": "Branch details"},
        401: {"description": "Unauthorized"},
        404: {"description": "Branch not found"},
    },
)
async def get_branch_endpoint(
    project_id: uuid.UUID,
    branch_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single branch by ID."""
    await _verify_project_access(session, project_id, auth.agent_id)
    svc = CoordinationService(session)
    branch = await svc.get_branch(branch_id)
    if branch is None or branch.project_id != project_id:
        raise HTTPException(status_code=404, detail="BRANCH_NOT_FOUND")

    return {
        "id": str(branch.id),
        "project_id": str(branch.project_id),
        "name": branch.name,
        "status": branch.status,
        "source_branch_id": str(branch.source_branch_id) if branch.source_branch_id else None,
        "created_by": str(branch.created_by),
        "task_id": str(branch.task_id) if branch.task_id else None,
        "created_at": branch.created_at.isoformat() if branch.created_at else None,
        "merged_at": branch.merged_at.isoformat() if branch.merged_at else None,
    }


@router.post(
    "/{project_id}/branches/{branch_id}/merge",
    response_model=MergeBranchResponse,
    responses={
        200: {"description": "Merge completed"},
        400: {"description": "Merge not possible (already merged, invalid status)"},
        401: {"description": "Unauthorized"},
        404: {"description": "Branch not found"},
        409: {"description": "Merge conflicts detected"},
    },
)
async def merge_branch_endpoint(
    project_id: uuid.UUID,
    branch_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> MergeBranchResponse:
    """Merge a branch into main."""
    await _verify_project_access(session, project_id, auth.agent_id)
    from loom.services.retrieval.queue import get_redis

    redis = None
    try:
        redis = get_redis()
    except Exception:
        pass

    svc = CoordinationService(session, redis)
    try:
        result = await svc.merge_branch(branch_id, auth.agent_id)
    except ValueError as exc:
        error_code = str(exc)
        if error_code == "BRANCH_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error_code)
        raise HTTPException(status_code=400, detail=error_code)
    except TimeoutError:
        raise HTTPException(status_code=409, detail="LOCK_ACQUISITION_FAILED")

    return MergeBranchResponse(
        status=result.status,
        merge_unit_id=result.merge_unit_id,
        conflict_ids=result.conflict_ids,
    )
