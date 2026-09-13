"""Contracts shared by every project-agent credential issuance path."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent
from loom.security import hash_api_key
from loom.services.accounts.credentials import issue_agent_credential


class StubSession:
    def __init__(self) -> None:
        self.added: Agent | None = None
        self.flushed = False

    def add(self, agent: Agent) -> None:
        self.added = agent

    async def flush(self) -> None:
        self.flushed = True


async def test_issued_agent_key_is_hashed_scoped_auditable_and_expiring() -> None:
    session = StubSession()
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    before = datetime.now(UTC)

    agent, raw_key = await issue_agent_credential(
        cast(AsyncSession, session),
        project_id=project_id,
        kind="local",
        name="Test CLI",
        created_by_user_id=user_id,
        lifetime=timedelta(minutes=10),
    )

    assert session.added is agent
    assert session.flushed is True
    assert agent.project_id == project_id
    assert agent.created_by_user_id == user_id
    assert agent.credentials_ref == hash_api_key(raw_key)
    assert raw_key not in agent.credentials_ref
    assert agent.key_hint == raw_key[-8:]
    assert agent.expires_at is not None
    assert before + timedelta(minutes=9) < agent.expires_at
