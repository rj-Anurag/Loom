"""Async summarization worker — periodically summarizes unsummarized context units.

Run as a standalone process::

    python -m loom.services.retrieval.summarizer

Or via the shell script::

    scripts/run-summarizer.sh
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from dataclasses import dataclass

import redis.asyncio as redis_async
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from loom.config import settings
from loom.models import Agent
from loom.models.context_units import ContextUnit
from loom.services.context.service import write_context
from loom.services.retrieval.grouping import (
    find_unsummarized_groups,
)
from loom.services.retrieval.providers import LLMProvider, from_llm_config

logger = logging.getLogger(__name__)

_shutdown: bool = False

SUMMARIZER_CREDENTIALS_REF = "__summarizer__"
"""Well-known credentials_ref for the summarizer agent identity."""


@dataclass
class SummarizationResult:
    """Result of a summarization cycle."""

    summary_count: int
    """Number of summaries created in this cycle."""
    groups_found: int = 0
    """Number of unsummarized groups identified."""
    groups_skipped: int = 0
    """Number of groups skipped (e.g. lock held, LLM failure)."""
    group_errors: int = 0
    """Number of groups that failed during summarization."""


def _handle_sigterm(signum: int, frame: object | None) -> None:  # noqa: ARG001
    """Set the shutdown flag so the worker loop exits gracefully."""
    global _shutdown  # noqa: PLW0603
    _shutdown = True
    logger.info("Received SIGTERM — shutting down after current cycle...")


async def _ensure_summarizer_agent(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> Agent:
    """Get or create the summarizer agent identity for a project.

    Returns the Agent.  The summarizer uses a well-known
    ``credentials_ref`` value of ``"__summarizer__"`` to identify
    itself across restarts.
    """
    # Look for existing summarizer agent
    existing = (
        await session.execute(
            select(Agent).where(
                Agent.project_id == project_id,
                Agent.credentials_ref == SUMMARIZER_CREDENTIALS_REF,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing

    # Create a new cloud-kind agent with the well-known credentials_ref
    agent = Agent(
        project_id=project_id,
        kind="system",
        credentials_ref=SUMMARIZER_CREDENTIALS_REF,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def run_summarization_cycle(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    llm: LLMProvider | None = None,
    redis: redis_async.Redis | None = None,
    window_minutes: int | None = None,
    max_units_per_group: int | None = None,
    min_units: int | None = None,
) -> SummarizationResult:
    """Run one summarization cycle for a single project.

    1. Acquire Redis project-level lock (``summarize:{project_id}``).
    2. Get or create the summarizer agent for the project.
    3. Find unsummarized groups via :func:`find_unsummarized_groups`.
    4. For each group: summarize via LLM, then write summary via
       :func:`write_context` with ``supersedes`` edges.
    5. Release the Redis lock.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    project_id : uuid.UUID
        Target project.
    llm : LLMProvider | None
        LLM provider.  Falls back to ``from_llm_config()`` if ``None``.
    redis : redis_async.Redis | None
        Redis client for distributed locking.  Lock is skipped if ``None``.
    window_minutes : int | None
        Override for ``summarization_window_minutes`` setting.
    max_units_per_group : int | None
        Override for ``summarization_max_units_per_group`` setting.
    min_units : int | None
        Override for ``summarization_min_units`` setting.

    Returns
    -------
    SummarizationResult
        Result with the count of summaries created.
    """
    # Resolve parameters from settings if not overridden
    _window = (
        window_minutes
        if window_minutes is not None
        else settings.summarization_window_minutes
    )
    _max_units = (
        max_units_per_group
        if max_units_per_group is not None
        else settings.summarization_max_units_per_group
    )
    _min_units = min_units if min_units is not None else settings.summarization_min_units

    # Resolve LLM provider
    llm_provider = llm if llm is not None else from_llm_config()

    # ── 1. Acquire Redis project lock ────────────────────────────────────
    lock_key = f"summarize:{project_id}"
    # Use a unique token so we can safely release only our own lock
    lock_token = str(uuid.uuid4())
    if redis is not None:
        lock_acquired = await redis.set(lock_key, lock_token, nx=True, ex=3600)  # 1 hour TTL
        if not lock_acquired:
            logger.info(
                "Summarization lock held by another worker — skipping project %s",
                project_id,
            )
            return SummarizationResult(0)

    try:
        # ── 2. Get/look up summarizer agent ──────────────────────────────
        summarizer_agent = await _ensure_summarizer_agent(session, project_id)

        # ── 3. Find unsummarized groups ──────────────────────────────────
        groups = await find_unsummarized_groups(
            session,
            project_id,
            window_minutes=_window,
            max_units_per_group=_max_units,
            min_units=_min_units,
        )

        if not groups:
            logger.info("No unsummarized groups found for project %s", project_id)
            return SummarizationResult(0)

        # ── 4. Summarize each group ──────────────────────────────────────
        summary_count = 0
        groups_skipped = 0
        group_errors = 0
        for group in groups:
            try:
                # Idempotency check: skip if summary already exists for this group
                existing = (
                    await session.execute(
                        select(ContextUnit).where(
                            ContextUnit.client_uuid == group.summary_client_uuid
                        )
                    )
                ).scalar_one_or_none()

                if existing is not None:
                    groups_skipped += 1
                    logger.info(
                        "Summary already exists for group %s — skipping",
                        group.sorted_ids_string,
                    )
                    continue

                # Build context unit dicts for the LLM
                group_dicts = [
                    {
                        "id": str(group.unit_ids[i]),
                        "content": group.contents[i],
                        "type": group.types[i],
                        "trust_tier": group.trust_tiers[i],
                        "created_at": group.created_ats[i].isoformat(),
                        "agent_id": str(group.agent_ids[i]),
                    }
                    for i in range(len(group.unit_ids))
                ]

                # Call the LLM
                summary_text = await llm_provider.summarize(group_dicts)
                if not summary_text:
                    groups_skipped += 1
                    logger.warning(
                        "LLM returned empty summary for group %s — skipping",
                        group.sorted_ids_string,
                    )
                    continue

                # Compute version as max(parent.version) + 1
                parent_versions = (
                    await session.execute(
                        text(
                            "SELECT version FROM context_units "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": group.unit_ids},
                    )
                ).scalars().all()
                max_version = max(parent_versions) if parent_versions else 0
                next_version = max_version + 1

                # Write the summary via write_context
                await write_context(
                    session,
                    project_id,
                    summarizer_agent.id,
                    client_uuid=group.summary_client_uuid,
                    type_="summary",
                    content=summary_text,
                    version=next_version,
                    trust_tier=group.highest_trust_tier,
                    parent_ids=group.unit_ids,
                    parent_relations=["supersedes"] * len(group.unit_ids),
                )

                summary_count += 1
                logger.info(
                    "Created summary for group %s (%d units)",
                    group.sorted_ids_string,
                    len(group.unit_ids),
                )

            except Exception:
                group_errors += 1
                logger.exception(
                    "Failed to summarize group %s — skipping",
                    group.sorted_ids_string,
                )
                continue

        return SummarizationResult(
            summary_count=summary_count,
            groups_found=len(groups),
            groups_skipped=groups_skipped,
            group_errors=group_errors,
        )

    finally:
        # ── 5. Release Redis lock ────────────────────────────────────────
        if redis is not None:
            try:
                # Only delete if the lock is still ours (compare-and-delete via Lua)
                release_script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("DEL", KEYS[1])
                end
                return 0
                """
                await redis.eval(release_script, 1, lock_key, lock_token)
            except Exception:
                logger.warning("Failed to release summarization lock %s", lock_key)


async def run_summarization_loop() -> None:
    """Main asyncio entry point for the summarization worker.

    Startup:
        1. Register SIGTERM handler.
        2. Create DB engine + session factory.
        3. Create LLM provider from config.
        4. Connect to Redis.
        5. Enter the periodic loop.

    Loop:
        1. Discover all projects (SELECT DISTINCT project_id FROM context_units).
        2. For each project, call ``run_summarization_cycle``.
        3. Sleep for ``settings.summarization_interval_minutes``.
        4. Continue until shutdown flag is set.
    """
    global _shutdown  # noqa: PLW0603

    # Register signal handler
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _handle_sigterm, signal.SIGTERM, None)

    # Create DB engine + session factory
    engine = create_async_engine(settings.async_database_url, echo=False)
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Create LLM provider
    llm_provider = from_llm_config()

    # Connect to Redis
    r = redis_async.from_url(settings.redis_url)

    interval_seconds = settings.summarization_interval_minutes * 60

    logger.info(
        "Summarization worker starting (provider=%s, interval=%ds)",
        settings.summarization_provider,
        interval_seconds,
    )

    while not _shutdown:
        try:
            async with async_session_factory() as session:
                # Discover all projects that have context units
                project_rows = (
                    await session.execute(
                        text("SELECT DISTINCT project_id FROM context_units")
                    )
                ).scalars().all()

                if not project_rows:
                    logger.debug("No projects found — skipping cycle")
                else:
                    for pid in project_rows:
                        if _shutdown:
                            break
                        result = await run_summarization_cycle(
                            session,
                            pid,
                            llm=llm_provider,
                            redis=r,
                        )
                        if result.summary_count > 0:
                            logger.info(
                                "Summarized %d group(s) for project %s",
                                result.summary_count,
                                pid,
                            )

            if _shutdown:
                break

            logger.debug(
                "Sleeping for %d seconds until next summarization cycle",
                interval_seconds,
            )
            # Sleep in small increments to respond to shutdown signals
            for _ in range(interval_seconds):
                if _shutdown:
                    break
                await asyncio.sleep(1)

        except Exception:
            logger.exception("Unexpected error in summarization loop")
            await asyncio.sleep(5)

    logger.info("Summarization worker shut down gracefully")


async def main() -> None:
    """Entry point — sets up logging and runs the loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting Loom summarization worker (provider=%s)", settings.summarization_provider)
    await run_summarization_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted — exiting")
