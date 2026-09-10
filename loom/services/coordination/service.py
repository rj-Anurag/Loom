"""Coordination Service — public API for locks, branches, and tasks.

Wraps the lower-level modules (``locks``, ``branches``, ``tasks``) into
a single ``CoordinationService`` class for easy dependency injection into
the Context Service and API routers.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import redis.asyncio as redis_async
from sqlalchemy.ext.asyncio import AsyncSession

from loom.services.coordination.branches import (
    MergeResult,
    create_branch,
    get_branch,
    list_branches,
    merge_branch,
)
from loom.services.coordination.locks import LockResult, acquire_lock, acquire_locks, release_lock
from loom.services.coordination.tasks import (
    assign_task,
    complete_task,
    create_task,
    fail_task,
    get_task,
    list_tasks,
    start_task,
)

if TYPE_CHECKING:
    from loom.models import Branch, Task


class CoordinationService:
    """Unified service for coordination operations.

    Provides locks, branches, and tasks with dependency injection for
    the database session and Redis client.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy async session.
    redis : redis_async.Redis | None
        Redis client for distributed locks.  ``None`` means all lock
        operations fall back to optimistic concurrency.
    """

    def __init__(
        self,
        session: AsyncSession,
        redis: redis_async.Redis | None = None,
    ) -> None:
        self.session = session
        self.redis = redis

    # ── Locks ─────────────────────────────────────────────────────────────

    async def acquire_lock(
        self,
        unit_id: str,
        agent_id: str,
        ttl: int = 30,
        retry_delay: float = 0.1,
        max_retries: int = 3,
    ) -> LockResult:
        return await acquire_lock(
            self.redis, unit_id, agent_id,
            ttl=ttl, retry_delay=retry_delay, max_retries=max_retries,
        )

    async def acquire_locks(
        self,
        unit_ids: list[str],
        agent_id: str,
        ttl: int = 30,
    ) -> list[LockResult]:
        return await acquire_locks(self.redis, unit_ids, agent_id, ttl=ttl)

    async def release_lock(self, unit_id: str, agent_id: str) -> bool:
        return await release_lock(self.redis, unit_id, agent_id)

    # ── Branches ──────────────────────────────────────────────────────────

    async def create_branch(
        self,
        project_id: uuid.UUID,
        name: str,
        agent_id: uuid.UUID,
        *,
        source_branch_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> Branch:
        return await create_branch(
            self.session, project_id, name, agent_id,
            source_branch_id=source_branch_id,
            task_id=task_id,
        )

    async def list_branches(
        self,
        project_id: uuid.UUID,
        status: str | None = None,
    ) -> list[Branch]:
        return await list_branches(self.session, project_id, status=status)

    async def get_branch(self, branch_id: uuid.UUID) -> Branch | None:
        return await get_branch(self.session, branch_id)

    async def merge_branch(
        self,
        branch_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> MergeResult:
        return await merge_branch(
            self.session, self.redis, branch_id, agent_id,
        )

    # ── Tasks ─────────────────────────────────────────────────────────────

    async def create_task(
        self,
        project_id: uuid.UUID,
        title: str,
        *,
        description: str | None = None,
        assigned_to: uuid.UUID | None = None,
    ) -> Task:
        return await create_task(
            self.session, project_id, title,
            description=description,
            assigned_to=assigned_to,
        )

    async def list_tasks(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Task]:
        return await list_tasks(self.session, project_id, status=status)

    async def get_task(self, task_id: uuid.UUID) -> Task | None:
        return await get_task(self.session, task_id)

    async def assign_task(
        self,
        task_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Task:
        return await assign_task(self.session, task_id, agent_id)

    async def start_task(
        self,
        task_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> Task:
        return await start_task(
            self.session, task_id, branch_id=branch_id,
        )

    async def complete_task(self, task_id: uuid.UUID) -> Task:
        return await complete_task(self.session, task_id)

    async def fail_task(self, task_id: uuid.UUID) -> Task:
        return await fail_task(self.session, task_id)
