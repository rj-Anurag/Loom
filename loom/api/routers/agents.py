from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.post("/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str) -> dict[str, Any]:
    return {"status": "ok"}


@router.post("/projects/{project_id}/agents")
async def register_agent(project_id: str) -> dict[str, Any]:
    return {"agent_id": "", "api_key": "", "trust_tier": "agent"}
