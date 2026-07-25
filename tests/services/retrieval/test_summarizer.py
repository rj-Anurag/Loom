"""Tests for the summarizer worker (Phase 2.2 — B2, E2).

The summarizer worker groups unsummarized context units, calls an LLM provider
to generate summaries, and writes ``summary``-type context units with
``supersedes`` edges to the originals.

These tests define the expected interface BEFORE any implementation exists
in ``loom/services/retrieval/summarizer.py``.

Red-phase failures expected:
  - ``ModuleNotFoundError`` for ``summarizer`` module
  - ``AttributeError`` for ``run_summarization_cycle``
  - DB constraint errors, missing tables, etc.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


class TestRunSummarizationCycle:
    """Integration tests for ``run_summarization_cycle``.

    Requires a real PostgreSQL connection.  Uses ``mock_redis`` so tests
    can run without a running Redis instance.
    """

    async def test_cycle_creates_summary_units(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """run_summarization_cycle creates summary-type context units."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        result = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert result.summary_count > 0

        # Verify summary units exist in the DB
        rows = (
            await db_session.execute(
                text(
                    "SELECT type FROM context_units "
                    "WHERE project_id = :pid AND type = 'summary'"
                ),
                {"pid": test_project.id},
            )
        ).all()
        assert len(rows) >= result.summary_count

    async def test_cycle_creates_supersedes_edges(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """Summary units have ``supersedes`` edges to original units."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        result = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        if result.summary_count > 0:
            edges = (
                await db_session.execute(
                    text("SELECT * FROM context_edges WHERE relation = 'supersedes'")
                )
            ).all()
            assert len(edges) > 0

    async def test_idempotent_double_run(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """Running summarization twice on the same units does NOT create duplicates."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        result1 = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert result1.summary_count > 0

        result2 = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert result2.summary_count == 0  # No new summaries on idempotent run

    async def test_no_unsummarized_units(
        self,
        db_session,
        test_project,
        stub_llm,
        mock_redis,
    ) -> None:
        """Cycle with no unsummarized units produces 0 summaries."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        result = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert result.summary_count == 0

    async def test_redis_lock_prevents_concurrent_runs(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """Project-level Redis lock prevents two concurrent summarization cycles."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        # Manually acquire the summarization lock using raw Redis SET NX
        # (matches the lock-key format the summarizer uses internally)
        lock_key = f"summarize:{test_project.id}"
        lock_acquired = await mock_redis.set(lock_key, "test-runner", nx=True, ex=60)
        assert lock_acquired is True

        # Cycle should skip since the lock is held by our "test-runner"
        result = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert result.summary_count == 0

    async def test_originals_still_queryable(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """Original units are NOT deleted after summarization."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        # Count originals before
        before = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM context_units "
                    "WHERE project_id = :pid AND type != 'summary'"
                ),
                {"pid": test_project.id},
            )
        ).scalar()

        await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )

        # Count originals after — should be identical
        after = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM context_units "
                    "WHERE project_id = :pid AND type != 'summary'"
                ),
                {"pid": test_project.id},
            )
        ).scalar()
        assert after == before


class TestSummarizerRunResult:
    """``run_summarization_cycle`` return value structure."""

    async def test_returns_summary_count(
        self,
        db_session,
        test_project,
        sample_units_in_window,
        stub_llm,
        mock_redis,
    ) -> None:
        """Return value has a ``summary_count`` field of type int."""
        from loom.services.retrieval.summarizer import run_summarization_cycle

        result = await run_summarization_cycle(
            db_session,
            test_project.id,
            llm=stub_llm,
            redis=mock_redis,
        )
        assert hasattr(result, "summary_count")
        assert isinstance(result.summary_count, int)
