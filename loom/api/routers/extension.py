from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from loom.db import get_session
from loom.services.extension.service import setup_extension

router = APIRouter()


class SetupResponse(BaseModel):
    id: str
    name: str
    created_at: str
    agent_id: str
    api_key: str


@router.get(
    "/v1/extension/setup",
    response_model=SetupResponse,
    responses={
        200: {"description": "Extension agent credentials"},
    },
)
async def setup_extension_endpoint(
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await setup_extension(session)
