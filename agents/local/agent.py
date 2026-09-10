"""Local Loom agent — demonstrates the full read → LLM → write loop.

Usage::

    # Basic: read context → LLM → write result
    python -m agents.local.agent --task "Design the auth flow" --project <uuid>

    # Dry-run (skip LLM call, just read + print)
    python -m agents.local.agent --task "Design the auth flow" --project <uuid> --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from typing import Any, cast

import httpx
from openai import AsyncOpenAI

from agents.local.config import AgentConfig, config

logger = logging.getLogger(__name__)


# ── Loom API helpers ──────────────────────────────────────────────────────────


class LoomClient:
    """Thin HTTP client for the Loom context API."""

    def __init__(
        self,
        cfg: AgentConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = cfg.loom_api_url.rstrip("/")
        self.api_key = cfg.loom_api_key
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=self.base_url)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def read_context(
        self,
        project_id: str,
        task_description: str,
        budget: int = 4096,
    ) -> list[dict[str, Any]]:
        """Call GET /v1/projects/{id}/context and return the units list."""
        resp = await self._http.get(
            f"/v1/projects/{project_id}/context",
            params={"query": task_description, "budget": budget, "scope": "task"},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = cast(dict[str, Any], resp.json())
        return cast(list[dict[str, Any]], data.get("units", []))

    async def write_context(
        self,
        project_id: str,
        content: str,
        *,
        version: int | None = None,
        type_: str = "task_result",
        parent_ids: list[str] | None = None,
        parent_relations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Call POST /v1/projects/{id}/context and return the response."""
        body: dict[str, Any] = {
            "client_uuid": str(uuid.uuid4()),
            "type": type_,
            "content": content,
        }
        body["version"] = version if version is not None else 1
        if parent_ids:
            body["parent_ids"] = parent_ids
        if parent_relations:
            body["parent_relations"] = parent_relations

        resp = await self._http.post(
            f"/v1/projects/{project_id}/context",
            json=body,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


# ── LLM helpers ───────────────────────────────────────────────────────────────


class GroqLLM:
    """LLM wrapper backed by Groq's OpenAI-compatible API."""

    def __init__(self, cfg: AgentConfig) -> None:
        self.model = cfg.llm_model
        self.api_key = cfg.groq_api_key
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=self.api_key,
            )
            if self.api_key
            else None
        )

    def _get_client(self) -> AsyncOpenAI:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required for non-dry-run agent execution")
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=self.api_key,
            )
        return self._client

    async def generate(self, prompt: str) -> str:
        """Send a prompt to Groq and return the text response."""
        resp = await self._get_client().chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI agent working in a multi-agent collaboration system. "
                        "Read the provided context and complete the task. "
                        "Write your result as a clear, structured response."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
        )
        return resp.choices[0].message.content or ""


# ── Agent loop ────────────────────────────────────────────────────────────────


class LocalAgent:
    """End-to-end local agent: read → LLM → write."""

    def __init__(
        self,
        cfg: AgentConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cfg = cfg or config
        self.loom = LoomClient(self.cfg, http_client=http_client)
        self.llm = GroqLLM(self.cfg)

    async def run(
        self,
        task_description: str,
        project_id: str | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute the full read → LLM → write loop.

        Parameters
        ----------
        task_description : str
            Natural-language description of what the agent should do.
        project_id : str | None
            Loom project UUID.  Falls back to ``LOOM_PROJECT_ID`` env var.
        dry_run : bool
            If ``True``, print the context and prompt but skip the LLM + write.

        Returns
        -------
        dict
            The API response from the write call (or a summary dict for dry-runs).
        """
        pid = project_id or self.cfg.default_project_id
        if not pid:
            msg = "No project_id provided and LOOM_PROJECT_ID is not set"
            raise ValueError(msg)

        # 1. Read context
        units = await self.loom.read_context(pid, task_description, self.cfg.read_budget)
        logger.info("Read %d context units", len(units))

        if dry_run:
            logger.info("DRY RUN — skipping LLM call and write")
            return {
                "task": task_description,
                "project_id": pid,
                "units_read": len(units),
                "status": "dry_run",
            }

        # 2. Build prompt
        context_block = "\n\n".join(
            f"[{u.get('type', 'unknown')}] {u['content'][:500]}"
            for u in units
        )
        prompt = (
            f"## Task\n{task_description}\n\n"
            f"## Relevant Context\n{context_block}\n\n"
            "## Response\nWrite your result below."
        )

        # 3. Call LLM
        logger.info("Calling LLM (model=%s)...", self.cfg.llm_model)
        response = await self.llm.generate(prompt)
        logger.info("LLM responded (%d chars)", len(response))

        # 4. Write result
        parent_ids = [u["id"] for u in units if "id" in u]
        parent_versions = [int(u["version"]) for u in units if "version" in u]
        expected_version = max(parent_versions) + 1 if parent_versions else 1
        result = await self.loom.write_context(
            pid,
            response,
            version=expected_version,
            type_="task_result",
            parent_ids=parent_ids if parent_ids else None,
        )
        logger.info("Wrote context unit %s", result.get("id"))
        return result

    async def close(self) -> None:
        await self.loom.close()


# ── CLI entry point ───────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Loom Local Agent — read → LLM → write loop"
    )
    parser.add_argument(
        "--task",
        required=True,
        help="Natural-language task description for the agent",
    )
    parser.add_argument(
        "--project",
        help="Loom project UUID (default: LOOM_PROJECT_ID env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM call and write — just read context and print",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    agent = LocalAgent()
    try:
        result = await agent.run(
            task_description=args.task,
            project_id=args.project,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
