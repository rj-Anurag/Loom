"""Tests for the summary score boost in the read path (Phase 2.2 — C1).

``_compute_score`` in ``loom/services/context/service.py`` needs an additional
``unit_type`` parameter that adds ``+0.15`` when the type is ``"summary"``.

These tests define the expected interface change BEFORE it is implemented.
They will fail with ``TypeError`` in the Red phase because ``_compute_score``
does not yet accept a ``unit_type`` keyword argument.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio


async def test_summary_score_boost_added() -> None:
    """``_compute_score`` adds ``+0.15`` for ``summary`` type units."""
    # The function currently lives in loom.services.context.service, not retrieval
    from loom.services.context.service import _compute_score

    now = datetime.now(timezone.utc)

    score_regular = _compute_score(
        ts_rank=0.5,
        created_at=now,
        trust_tier="agent",
        unit_type="message",
    )
    score_summary = _compute_score(
        ts_rank=0.5,
        created_at=now,
        trust_tier="agent",
        unit_type="summary",
    )

    assert abs(score_summary - score_regular - 0.15) < 0.001


async def test_summary_boost_non_summary_types() -> None:
    """Non-summary types get no boost (0.0 bonus)."""
    from loom.services.context.service import _compute_score

    now = datetime.now(timezone.utc)

    for t in ("message", "decision", "artifact_ref", "task_result"):
        score = _compute_score(
            ts_rank=0.5,
            created_at=now,
            trust_tier="agent",
            unit_type=t,
        )
        summary_score = _compute_score(
            ts_rank=0.5,
            created_at=now,
            trust_tier="agent",
            unit_type="summary",
        )
        assert summary_score > score
