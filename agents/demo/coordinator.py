"""Demo coordinator — orchestrates the 3-agent concurrent demo.

Usage::

    python -m agents.demo.coordinator [--api-url http://localhost:8000]

This creates a fresh project, registers 3 agents, runs them concurrently,
and reports results.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from agents.demo.base import DemoAgentResult
from agents.demo.stubs import LoginFormAgent, PasswordAgent, SessionAgent
from agents.local.agent import LoomClient
from agents.local.config import AgentConfig

logger = logging.getLogger(__name__)


@dataclass
class DemoReport:
    """Structured report of the demo run."""

    project_id: str
    project_name: str
    agents_completed: int
    total_writes: int
    agent_results: list[DemoAgentResult] = field(default_factory=list)
    wall_clock_seconds: float = 0.0

    def print_summary(self) -> None:
        """Print a formatted summary to stdout."""
        print()
        print("=" * 60)
        print(f"  Demo Complete: {self.project_name}")
        print(f"  Project ID:   {self.project_id}")
        print(f"  Wall clock:   {self.wall_clock_seconds:.1f}s")
        print(f"  Agents:       {self.agents_completed}")
        print(f"  Total writes: {self.total_writes}")
        print("=" * 60)
        for r in self.agent_results:
            print(f"  {r.agent_name} ({r.agent_kind}) — {r.writes_count} writes")
            for uid in r.unit_ids[:2]:
                print(f"    ├─ {uid}")
            if len(r.unit_ids) > 2:
                print(f"    └─ ... and {len(r.unit_ids) - 2} more")
        print()

    def to_json(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "agents_completed": self.agents_completed,
            "total_writes": self.total_writes,
            "wall_clock_seconds": self.wall_clock_seconds,
            "agent_results": [
                {
                    "agent_name": r.agent_name,
                    "agent_kind": r.agent_kind,
                    "writes_count": r.writes_count,
                    "unit_ids": r.unit_ids,
                }
                for r in self.agent_results
            ],
        }


# ── API helpers (no-auth bootstrap) ──────────────────────────────────────────


async def _bootstrap_project(api_url: str) -> tuple[str, str, str]:
    """Use the extension setup endpoint to create a project and first agent.

    Returns (project_id, project_name, agent_token).
    """
    async with httpx.AsyncClient(base_url=api_url) as client:
        resp = await client.get("/v1/extension/setup")
        resp.raise_for_status()
        data = cast(dict[str, Any], resp.json())
        return str(data["id"]), str(data["name"]), str(data["api_key"])


async def _register_demo_agent(
    api_url: str,
    project_id: str,
    kind: str,
    name: str,
    owner_api_key: str,
) -> str:
    """Register a new demo agent and return its token (api_key)."""
    async with httpx.AsyncClient(base_url=api_url) as client:
        resp = await client.post(
            f"/v1/projects/{project_id}/agents",
            json={"kind": kind, "name": name},
            headers={"Authorization": f"Bearer {owner_api_key}"},
        )
        resp.raise_for_status()
        data = cast(dict[str, Any], resp.json())
        return str(data["api_key"])


def _make_loom_client(api_url: str, api_key: str) -> LoomClient:
    """Create a LoomClient with the given credentials."""
    cfg = AgentConfig(loom_api_url=api_url, loom_api_key=api_key)
    return LoomClient(cfg)


# ── Coordinator ──────────────────────────────────────────────────────────────


class DemoCoordinator:
    """Runs the 3-agent concurrent demo.

    Flow:
    1. Bootstrap project + first agent via extension setup.
    2. Register 2 more agents (local, cloud) via registration endpoint.
    3. Write an initial project spec as the shared parent.
    4. Run all 3 agents concurrently via ``asyncio.gather()``.
    5. Report results.
    """

    def __init__(self, api_url: str = "http://localhost:8000") -> None:
        self.api_url = api_url.rstrip("/")

    async def run(self) -> DemoReport:
        """Execute the full demo and return the report."""
        start = time.monotonic()

        # 1. Bootstrap project + browser agent
        print("Bootstrapping project...")
        project_id, project_name, browser_token = await _bootstrap_project(
            self.api_url
        )
        print(f"  Project: {project_name} ({project_id})")

        # 2. Register 2 more agents
        print("Registering agents...")
        local_token = await _register_demo_agent(
            self.api_url,
            project_id,
            "local",
            "Agent A — Password Hashing",
            browser_token,
        )
        cloud_token = await _register_demo_agent(
            self.api_url,
            project_id,
            "cloud",
            "Agent B — Session Management",
            browser_token,
        )
        print(f"  Agent A (local):  {local_token[:8]}...")
        print(f"  Agent B (cloud):  {cloud_token[:8]}...")
        print(f"  Agent C (browser): {browser_token[:8]}...")

        # 3. Write initial project spec (browser agent writes this)
        spec_client = _make_loom_client(self.api_url, browser_token)
        spec = await spec_client.write_context(
            project_id=project_id,
            content=(
                "Project spec: Build a User Authentication System. "
                "Components: password hashing, session management, login form."
            ),
            version=1,
            type_="message",
        )
        print(f"  Initial spec written (id={spec.get('id', '?')[:8]}...)")

        # 4. Create agents
        agents = [
            PasswordAgent(
                _make_loom_client(self.api_url, local_token),
                "Agent A — Password Hashing",
                "local",
                num_writes=3,
            ),
            SessionAgent(
                _make_loom_client(self.api_url, cloud_token),
                "Agent B — Session Management",
                "cloud",
                num_writes=3,
            ),
            LoginFormAgent(
                _make_loom_client(self.api_url, browser_token),
                "Agent C — Login Form",
                "browser",
                num_writes=3,
            ),
        ]

        # 5. Run all 3 agents concurrently
        print("Running agents concurrently...")
        results = await asyncio.gather(
            *[a.run(project_id, a.agent_name) for a in agents],
            return_exceptions=True,
        )

        # Check for errors
        agent_results: list[DemoAgentResult] = []
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.error("Agent %d failed: %s", i, r)
                print(f"  Agent {i} FAILED: {r}")
            else:
                agent_results.append(r)

        wall = time.monotonic() - start

        report = DemoReport(
            project_id=project_id,
            project_name=project_name,
            agents_completed=len(agent_results),
            total_writes=sum(r.writes_count for r in agent_results),
            agent_results=agent_results,
            wall_clock_seconds=wall,
        )

        return report


# ── CLI entry point ──────────────────────────────────────────────────────────


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Agent Concurrent Demo (Phase 2.6)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Loom API base URL",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (for CI)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    coordinator = DemoCoordinator(api_url=args.api_url)
    report = await coordinator.run()
    report.print_summary()

    if args.json:
        print("---JSON---")
        print(__import__("json").dumps(report.to_json(), indent=2))

    sys.exit(0 if report.agents_completed == 3 else 1)


if __name__ == "__main__":
    asyncio.run(_main())
