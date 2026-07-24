"""Authentication middleware for the Loom API.

Provides FastAPI dependencies that extract and verify bearer tokens,
and validate project-level access.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.db import get_session
from loom.models import Agent


class AuthContext:
    """Represents an authenticated agent."""

    def __init__(self, agent_id: uuid.UUID) -> None:
        self.agent_id = agent_id


async def require_auth(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """Extract and validate the Bearer token → Agent mapping.

    For MVP the token is the agent's UUID directly.  Returns 401 if the
    token is missing, malformed, or does not match a known agent.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization scheme")

    token = authorization.removeprefix("Bearer ")
    try:
        agent_id = uuid.UUID(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed token")

    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=401, detail="Unknown agent")

    return AuthContext(agent_id=agent.id)
