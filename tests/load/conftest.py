"""Fixtures for the concurrent-merge load test (Phase 1.12).

Provides ``AgentSimulator``, a helper that encapsulates one agent's
auth context and the HTTP client, plus project / agent fixtures.
"""

from __future__ import annotations

import time
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.main import app
from loom.models import Agent, Project


class AgentSimulator:
    """Simulates an agent writing context units to the Loom API.

    Collects per-write latency so the load test can produce p50/p95/p99
    metrics.
    """

    def __init__(self, agent_id: uuid.UUID, api_key: str, client: AsyncClient, name: str) -> None:
        self.agent_id = agent_id
        self.api_key = api_key
        self._client = client
        self.name = name
        self.latencies: list[float] = []  # ms per write

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def write_context(
        self,
        project_id: str,
        content: str,
        *,
        version: int = 1,
        type_: str = "task_result",
        parent_ids: list[str] | None = None,
        parent_relations: list[str] | None = None,
    ) -> dict:
        """Write one context unit and record latency.  Returns the response JSON."""
        body: dict = {
            "client_uuid": str(uuid.uuid4()),
            "type": type_,
            "content": content,
            "version": version,
        }
        if parent_ids:
            body["parent_ids"] = parent_ids
        if parent_relations:
            body["parent_relations"] = parent_relations

        start = time.perf_counter()
        resp = await self._client.post(
            f"/v1/projects/{project_id}/context",
            json=body,
            headers=self._headers,
        )
        elapsed = (time.perf_counter() - start) * 1000  # ms
        self.latencies.append(elapsed)

        data = resp.json()
        data["_status"] = resp.status_code
        data["_latency_ms"] = round(elapsed, 1)
        return data

    async def write_batch(
        self,
        project_id: str,
        count: int,
        *,
        parent_ids: list[str] | None = None,
        base_content: str = "Write",
    ) -> list[dict]:
        """Write *count* context units sequentially and return results."""
        results = []
        for i in range(count):
            # Ensure unique content per write within the batch
            content = f"{base_content} ({self.name} batch {i}): "
            if parent_ids:
                # Non-overlapping content for auto-merge validation
                content += (
                    f"Implement feature module-{self.name}-{i} in src/features/{self.name}/{i}.py"
                )
                version = 2  # parent is version 1, so children must be version 2
            else:
                content += f"Independent analysis-{self.name}-{i} about project requirements"
                version = 1

            result = await self.write_context(
                project_id,
                content,
                version=version,
                parent_ids=parent_ids,
            )
            results.append(result)

        return results


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def load_client() -> AsyncClient:
    """Single ASGI transport client shared across the load test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def load_project(db_session: AsyncSession) -> Project:
    p = Project(name="Load Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def load_agents(
    db_session: AsyncSession,
    load_project: Project,
) -> list[Agent]:
    """Create 3 agents (auth, schema, api) for the load test."""
    agents_data = [
        ("auth-agent", "auth"),
        ("schema-agent", "schema"),
        ("api-agent", "api"),
    ]
    agents = []
    for name, kind in agents_data:
        a = Agent(project_id=load_project.id, kind="local")
        db_session.add(a)
        await db_session.flush()
        await db_session.refresh(a)
        agents.append(a)
    await db_session.commit()
    return agents
