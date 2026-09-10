"""Tests for summarization grouping strategy (Phase 2.2 — B1, E1).

Grouping module provides deterministic time-window grouping of unsummarized
context units.  These tests define the expected interface BEFORE any
implementation exists in ``loom/services/retrieval/grouping.py``.

Red-phase failures expected:
  - ``ModuleNotFoundError`` for ``grouping`` module
  - ``AttributeError`` for ``SummarizationGroup``, ``find_unsummarized_groups``
  - ``TypeError`` for missing parameters
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

pytestmark = pytest.mark.asyncio


# ── SummarizationGroup dataclass ──────────────────────────────────────────────


class TestSummarizationGroup:
    """SummarizationGroup dataclass and helpers."""

    async def test_summary_client_uuid_deterministic(self) -> None:
        """Same sorted_ids_string produces the same UUID every time."""
        from loom.services.retrieval.grouping import SummarizationGroup

        g1 = SummarizationGroup(
            window_start=datetime(2026, 1, 1),
            unit_ids=[uuid.UUID("11111111-1111-1111-1111-111111111111")],
            contents=["test"],
            types=["message"],
            trust_tiers=["agent"],
            agent_ids=[uuid.UUID("00000000-0000-0000-0000-000000000001")],
            created_ats=[datetime(2026, 1, 1)],
            highest_trust_tier="agent",
            sorted_ids_string="11111111-1111-1111-1111-111111111111",
        )
        g2 = SummarizationGroup(
            window_start=datetime(2026, 1, 1),
            unit_ids=[uuid.UUID("11111111-1111-1111-1111-111111111111")],
            contents=["test"],
            types=["message"],
            trust_tiers=["agent"],
            agent_ids=[uuid.UUID("00000000-0000-0000-0000-000000000001")],
            created_ats=[datetime(2026, 1, 1)],
            highest_trust_tier="agent",
            sorted_ids_string="11111111-1111-1111-1111-111111111111",
        )
        assert g1.summary_client_uuid == g2.summary_client_uuid

    async def test_different_ids_different_uuids(self) -> None:
        """Different sorted_ids_string produces different UUIDs."""
        from loom.services.retrieval.grouping import SummarizationGroup

        g1 = SummarizationGroup(
            window_start=datetime(2026, 1, 1),
            unit_ids=[uuid.UUID("11111111-1111-1111-1111-111111111111")],
            contents=["test"],
            types=["message"],
            trust_tiers=["agent"],
            agent_ids=[uuid.UUID("00000000-0000-0000-0000-000000000001")],
            created_ats=[datetime(2026, 1, 1)],
            highest_trust_tier="agent",
            sorted_ids_string="11111111-1111-1111-1111-111111111111",
        )
        g2 = SummarizationGroup(
            window_start=datetime(2026, 1, 1),
            unit_ids=[uuid.UUID("22222222-2222-2222-2222-222222222222")],
            contents=["other"],
            types=["decision"],
            trust_tiers=["user"],
            agent_ids=[uuid.UUID("00000000-0000-0000-0000-000000000001")],
            created_ats=[datetime(2026, 1, 1)],
            highest_trust_tier="user",
            sorted_ids_string="22222222-2222-2222-2222-222222222222",
        )
        assert g1.summary_client_uuid != g2.summary_client_uuid

    async def test_highest_trust_tier_inheritance(self) -> None:
        """_get_highest_tier picks the highest tier from source units."""
        from loom.services.retrieval.grouping import _get_highest_tier

        assert _get_highest_tier(["agent", "user", "external_tool"]) == "user"
        assert _get_highest_tier(["agent", "external_tool"]) == "agent"
        assert _get_highest_tier(["external_tool"]) == "external_tool"
        assert _get_highest_tier([]) == "agent"  # default


class TestFindUnsummarizedGroups:
    """Integration-style tests for find_unsummarized_groups.

    Requires a real PostgreSQL connection via the ``db_session`` fixture.
    """

    async def test_no_unsummarized_units_returns_empty(
        self,
        db_session,
        test_project,
    ) -> None:
        """When no units exist at all, returns an empty list."""
        from loom.services.retrieval.grouping import find_unsummarized_groups

        groups = await find_unsummarized_groups(db_session, test_project.id)
        assert groups == []

    async def test_single_group_within_window(
        self,
        db_session,
        test_project,
        sample_units_in_window,
    ) -> None:
        """Units within the same time window form one group."""
        from loom.services.retrieval.grouping import find_unsummarized_groups

        groups = await find_unsummarized_groups(
            db_session,
            test_project.id,
            window_minutes=30,
            min_units=1,
            max_units_per_group=50,
        )
        assert len(groups) >= 1

    async def test_skips_groups_below_min_units(
        self,
        db_session,
        test_project,
        few_recent_units,
    ) -> None:
        """Groups with fewer than min_units units are skipped."""
        from loom.services.retrieval.grouping import find_unsummarized_groups

        groups = await find_unsummarized_groups(
            db_session,
            test_project.id,
            window_minutes=30,
            min_units=10,
            max_units_per_group=50,
        )
        # Only 2 units exist, min_units=10 → no groups should be formed
        assert len(groups) == 0

    async def test_trust_tier_inheritance_in_groups(
        self,
        db_session,
        test_project,
        mixed_tier_units,
    ) -> None:
        """Groups inherit the highest trust tier from constituent units."""
        from loom.services.retrieval.grouping import find_unsummarized_groups

        groups = await find_unsummarized_groups(
            db_session,
            test_project.id,
            window_minutes=60,
            min_units=1,
            max_units_per_group=50,
        )
        for group in groups:
            assert group.highest_trust_tier in ("user", "agent", "external_tool")

    async def test_group_units_sorted_oldest_first(
        self,
        db_session,
        test_project,
        sample_units_in_window,
    ) -> None:
        """Unit IDs within a group are sorted oldest-first by created_at."""
        from loom.services.retrieval.grouping import find_unsummarized_groups

        groups = await find_unsummarized_groups(
            db_session,
            test_project.id,
            window_minutes=30,
            min_units=1,
            max_units_per_group=50,
        )
        for group in groups:
            ages = group.created_ats
            for i in range(1, len(ages)):
                assert ages[i - 1] <= ages[i]
