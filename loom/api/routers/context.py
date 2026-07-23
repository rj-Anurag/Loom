from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/{project_id}/context")
async def read_context(project_id: str) -> dict[str, Any]:
    return {"project_id": project_id, "units": [], "total_tokens": 0}


@router.post("/{project_id}/context", status_code=201)
async def write_context(project_id: str) -> dict[str, Any]:
    return {"id": "", "client_uuid": "", "created_at": "", "version": 1}
