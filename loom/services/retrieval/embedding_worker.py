"""Async embedding worker — consumes jobs from Redis and updates pgvector.

Run as a standalone process::

    python -m loom.services.retrieval.embedding_worker

Or via the shell script::

    scripts/run-embedding-worker.sh
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from loom.config import settings
from loom.models.context_units import ContextUnit
from loom.services.retrieval.providers import from_config
from loom.services.retrieval.queue import (
    DLQ_KEY,
    INPROGRESS_KEY,
    MAX_ATTEMPTS,
    QUEUE_KEY,
    get_redis,
)

logger = logging.getLogger(__name__)

_shutdown: bool = False


def _handle_sigterm(signum: int, frame: object | None) -> None:  # noqa: ARG001
    """Set the shutdown flag so the worker loop exits gracefully."""
    global _shutdown  # noqa: PLW0603
    _shutdown = True
    logger.info("Received SIGTERM — shutting down after current job...")



async def recover_inprogress() -> int:
    """On startup, move any orphaned in-progress jobs back to the main queue.

    Jobs left in ``embedding:inprogress`` after a worker crash are re-queued
    so another worker (or this one) picks them up.

    Returns the number of jobs recovered.
    """
    r = get_redis()
    count = 0
    while True:
        item = await r.rpoplpush(INPROGRESS_KEY, QUEUE_KEY)
        if item is None:
            break
        count += 1
    if count:
        logger.info("Recovered %d orphaned jobs from in-progress list", count)
    return count


async def process_embedding_job(
    context_unit_id: uuid.UUID,
    content: str,
) -> None:
    """Compute embedding for a single context unit and update the DB.

    Parameters
    ----------
    context_unit_id : uuid.UUID
        The target context unit's ID.
    content : str
        The unit's text content (may be truncated from the queue payload).

    Notes
    -----
    This function is also exposed for direct testing — test suites can
    call it with a synthetic unit without running the full worker loop.
    """
    # Fetch the unit to ensure it exists
    engine = create_async_engine(settings.async_database_url, echo=False)
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    provider = from_config()

    async with async_session_factory() as session:
        try:
            # Verify the unit exists
            row = (
                await session.execute(
                    text("SELECT 1 FROM context_units WHERE id = :id"),
                    {"id": context_unit_id},
                )
            ).one_or_none()

            if row is None:
                logger.warning(
                    "Context unit %s not found — skipping embedding job",
                    context_unit_id,
                )
                return

            # Compute embedding (None for empty content → leave as NULL)
            vector = await provider.embed(content)
            if vector is None:
                logger.info(
                    "Empty content for unit %s — skipping embedding",
                    context_unit_id,
                )
                return

            # All providers must produce vectors compatible with the shared
            # pgvector column. LocalProvider pads its native 384 dimensions.
            expected_dim = 1536
            if len(vector) != expected_dim:
                raise ValueError(
                    f"Expected {expected_dim}-dim vector, got {len(vector)} dim "
                    f"for unit {context_unit_id}"
                )

            # Update the DB via ORM (handles pgvector type correctly)
            unit = await session.get(ContextUnit, context_unit_id)
            if unit is None:
                logger.warning("Unit %s not found — skipping", context_unit_id)
                return
            unit.embedding = vector
            await session.commit()
            logger.info("Embedded unit %s successfully", context_unit_id)
        except Exception:
            await session.rollback()
            raise


async def main() -> None:
    """Entry point for the embedding worker process.

    Startup:
        1. Register SIGTERM handler.
        2. Recover orphaned in-progress jobs.
        3. Enter the job-processing loop.

    Loop:
        1. ``BRPOPLPUSH`` from ``embedding:queue`` → ``embedding:inprogress``
           with a 30-second timeout (allows checking the shutdown flag).
        2. Call :func:`process_embedding_job` to do the work.
        3. ``LREM`` from ``embedding:inprogress`` on success.
        4. On failure, increment attempt counter and either re-queue or DLQ.
    """
    global _shutdown  # noqa: PLW0701 — referenced for the flag

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Embedding worker starting (provider=%s)", settings.embedding_provider)

    # Register signal handler
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, _handle_sigterm, signal.SIGTERM, None)

    r = get_redis()

    # Recover orphaned jobs
    recovered = await recover_inprogress()
    if recovered:
        logger.info("Recovered %d orphaned jobs on startup", recovered)

    logger.info("Entering job-processing loop")

    while not _shutdown:
        try:
            # Blocking pop with timeout — returns None if no job within 30s
            job_data = await r.brpoplpush(
                QUEUE_KEY, INPROGRESS_KEY, timeout=30
            )
            if job_data is None:
                continue
            if isinstance(job_data, bytes):
                job_data = job_data.decode("utf-8")

            job: dict[str, Any] = json.loads(job_data)
            unit_id = uuid.UUID(job["context_unit_id"])
            content = job.get("content", "")
            attempt = job.get("attempt", 0)

            logger.info(
                "Processing embedding job for unit %s (attempt %d/%d)",
                unit_id,
                attempt + 1,
                MAX_ATTEMPTS,
            )

            try:
                await process_embedding_job(unit_id, content)
                await r.lrem(INPROGRESS_KEY, 0, job_data)
                logger.info("Successfully embedded unit %s", unit_id)

            except Exception:
                logger.exception("Failed to embed unit %s", unit_id)
                attempt += 1
                if attempt >= MAX_ATTEMPTS:
                    # Route to DLQ
                    failed_job = {
                        **job,
                        "attempt": attempt,
                        "error": str(sys.exc_info()[1]),
                    }
                    await r.lpush(DLQ_KEY, json.dumps(failed_job))
                    await r.lrem(INPROGRESS_KEY, 0, job_data)
                    logger.error(
                        "Job for unit %s exceeded max attempts — moved to DLQ",
                        unit_id,
                    )
                else:
                    # Re-queue for retry
                    retry_job = {**job, "attempt": attempt}
                    await r.lpush(QUEUE_KEY, json.dumps(retry_job))
                    await r.lrem(INPROGRESS_KEY, 0, job_data)
                    logger.info(
                        "Re-queued job for unit %s (attempt %d/%d)",
                        unit_id,
                        attempt,
                        MAX_ATTEMPTS,
                    )

        except Exception:
            logger.exception("Unexpected error in worker loop")
            await asyncio.sleep(1)

    logger.info("Worker shut down gracefully")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted — exiting")
