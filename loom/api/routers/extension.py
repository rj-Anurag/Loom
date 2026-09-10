from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.db import get_session
from loom.services.extension.service import setup_extension

router = APIRouter()


class SetupResponse(BaseModel):
    id: str
    name: str
    created_at: str
    agent_id: str
    api_key: str


def validate_bootstrap_request(presented_token: str | None) -> None:
    """Allow open local setup, but never anonymous credential minting in production."""
    configured_token = settings.bootstrap_token
    if not configured_token:
        if settings.environment.lower() == "development":
            return
        raise HTTPException(status_code=503, detail="BOOTSTRAP_TOKEN_NOT_CONFIGURED")

    if presented_token is None or not secrets.compare_digest(
        presented_token,
        configured_token,
    ):
        raise HTTPException(status_code=401, detail="INVALID_BOOTSTRAP_TOKEN")


@router.get(
    "/v1/extension/setup",
    response_model=SetupResponse,
    responses={
        200: {"description": "Extension agent credentials"},
    },
)
async def setup_extension_endpoint(
    bootstrap_token: str | None = Header(None, alias="X-Loom-Bootstrap-Token"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    validate_bootstrap_request(bootstrap_token)
    return await setup_extension(session)
