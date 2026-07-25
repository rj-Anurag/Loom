"""Tests for the hybrid search module (Phase 2.3).

These tests define the expected interface BEFORE implementation.
They will fail initially (Red phase)::

  - ``search.py`` module does not exist yet
  - ``encode_query``, ``vector_search``, etc. do not exist yet
"""

from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from loom.models import Agent

# ── Encode Query Tests ──────────────────────────────────────────────────────────


class TestEncodeQuery:
    """Tests for encode_query — query string → embedding vector."""

    @pytest.mark.asyncio
    async def test_encode_query_returns_vector(self) -> None:
        """StubProvider returns 1536-dim vector for a query."""
        from loom.services.retrieval.search import encode_query

        vector = await encode_query("authentication security")
        assert isinstance(vector, list)
        assert len(vector) == 1536
        assert all(isinstance(v, float) for v in vector)

    @pytest.mark.asyncio
    async def test_encode_query_empty_returns_none(self) -> None:
        """Empty string returns None."""
        from loom.services.retrieval.search import encode_query

        assert await encode_query("") is None
        assert await encode_query("   ") is None
        assert await encode_query("\t\n") is None

    @pytest.mark.asyncio
    async def test_encode_query_singleton_reuse(self) -> None:
        """Multiple calls reuse the same provider instance."""
        from loom.services.retrieval import search as search_module

        # Reset singleton state so the test starts clean
        importlib.reload(search_module)

        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.5] * 1536

        with patch(
            "loom.services.retrieval.search.from_config",
            return_value=mock_provider,
        ) as mock_from_config:
            await search_module.encode_query("first query")
            await search_module.encode_query("second query")

            # from_config should only be called once (singleton cached)
            mock_from_config.assert_called_once()
            assert mock_provider.embed.call_count == 2

    @pytest.mark.asyncio
    async def test_encode_query_propagates_provider_errors(self) -> None:
        """Provider exceptions are propagated to the caller."""
        from loom.services.retrieval import search as search_module

        importlib.reload(search_module)

        mock_provider = AsyncMock()
        mock_provider.embed.side_effect = RuntimeError("API unavailable")

        with patch(
            "loom.services.retrieval.search.from_config",
            return_value=mock_provider,
        ):
            with pytest.raises(RuntimeError, match="API unavailable"):
                await search_module.encode_query("test")


# ── Vector Search Tests ─────────────────────────────────────────────────────────


class TestVectorSearch:
    """Tests for vector_search — pgvector ANN cosine similarity."""

    @pytest.mark.asyncio
    async def test_vector_search_returns_results(
        self,
        db_session,
        test_project,
        stub_embedder,
        embedded_sample_units,
    ) -> None:
        """With existing units that have embeddings, returns results ranked by
        cosine similarity."""
        from loom.services.retrieval.search import vector_search

        query_embedding = await stub_embedder.embed("authentication security")
        results = await vector_search(db_session, test_project.id, query_embedding)

        assert len(results) > 0
        for r in results:
            assert "vector_score" in r
            assert isinstance(r["vector_score"], float)
            assert "id" in r
            assert "type" in r
            assert "trust_tier" in r
            assert "content" in r
            assert "created_at" in r
            assert "agent_id" in r

        # Results should be sorted by vector_score descending
        scores = [r["vector_score"] for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    @pytest.mark.asyncio
    async def test_vector_search_empty_project(
        self,
        db_session,
        test_project,
        stub_embedder,
    ) -> None:
        """No matching units returns empty list."""
        from loom.services.retrieval.search import vector_search

        query_embedding = await stub_embedder.embed("test")
        results = await vector_search(db_session, test_project.id, query_embedding)

        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_respects_scope_filter(
        self,
        db_session,
        test_project,
        test_agent,
        stub_embedder,
    ) -> None:
        """When scope_type_filter='summary', returns only summary-type units."""
        from loom.services.retrieval.search import vector_search

        # Insert a summary unit with embedding
        summary_embedding = await stub_embedder.embed("Project overview summary")
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, CAST(:embedding AS vector), :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "summary",
                "tier": "agent",
                "content": "Project overview summary for testing scope filter",
                "embedding": str(summary_embedding),
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        query_embedding = await stub_embedder.embed("project")
        results = await vector_search(
            db_session,
            test_project.id,
            query_embedding,
            scope_type_filter="summary",
        )

        assert len(results) > 0
        for r in results:
            assert r["type"] == "summary"

    @pytest.mark.asyncio
    async def test_vector_search_excludes_null_embeddings(
        self,
        db_session,
        test_project,
        test_agent,
        stub_embedder,
        embedded_sample_units,
    ) -> None:
        """Units with NULL embeddings are excluded."""
        from loom.services.retrieval.search import vector_search

        # Insert a unit without embedding
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, NULL, :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "message",
                "tier": "agent",
                "content": "Unit without embedding should not appear",
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        query_embedding = await stub_embedder.embed("test")
        results = await vector_search(db_session, test_project.id, query_embedding)
        contents = [r["content"] for r in results]
        assert all("without embedding" not in c for c in contents)


# ── Keyword Search Tests ────────────────────────────────────────────────────────


class TestKeywordSearch:
    """Tests for keyword_search — GIN full-text search."""

    @pytest.mark.asyncio
    async def test_keyword_search_returns_results(
        self,
        db_session,
        test_project,
        embedded_sample_units,
    ) -> None:
        """With matching units, returns keyword-ranked results."""
        from loom.services.retrieval.search import keyword_search

        results = await keyword_search(db_session, test_project.id, "bcrypt")

        assert len(results) > 0
        for r in results:
            assert "keyword_score" in r
            assert isinstance(r["keyword_score"], float)
            assert "id" in r
            assert "type" in r
            assert "trust_tier" in r
            assert "content" in r
            assert "created_at" in r
            assert "agent_id" in r

    @pytest.mark.asyncio
    async def test_keyword_search_no_match(
        self,
        db_session,
        test_project,
        embedded_sample_units,
    ) -> None:
        """Non-matching query returns empty list."""
        from loom.services.retrieval.search import keyword_search

        results = await keyword_search(
            db_session, test_project.id, "xyznonexistentkeyword"
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_keyword_search_respects_scope_filter(
        self,
        db_session,
        test_project,
        test_agent,
        embedded_sample_units,
    ) -> None:
        """When scope_type_filter='summary', returns only summary-type units."""
        from loom.services.retrieval.search import keyword_search

        # Insert a summary unit (embedded_sample_units are all "decision")
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, 'summary', :tier,
                     :content, NULL, :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "tier": "agent",
                "content": "Summary about bcrypt security decisions",
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        results = await keyword_search(
            db_session,
            test_project.id,
            "bcrypt",
            scope_type_filter="summary",
        )

        assert len(results) > 0
        for r in results:
            assert r["type"] == "summary"


# ── RRF Fusion Tests ────────────────────────────────────────────────────────────


class TestRrfFusion:
    """Tests for rrf_fusion — pure function, no DB needed."""

    def test_combines_two_lists(self) -> None:
        """RRF correctly fuses two ranked lists using SUM(1/(k+rank))."""
        from loom.services.retrieval.search import rrf_fusion

        vector_results = [
            {"id": "a", "content": "A from vector"},
            {"id": "b", "content": "B from vector"},
            {"id": "c", "content": "C from vector"},
        ]
        keyword_results = [
            {"id": "b", "content": "B from keyword"},
            {"id": "d", "content": "D from keyword"},
        ]

        fused = rrf_fusion(vector_results, keyword_results, k=60)

        # All IDs present
        fused_ids = [u["id"] for u in fused]
        assert "a" in fused_ids
        assert "b" in fused_ids
        assert "c" in fused_ids
        assert "d" in fused_ids

        # "b" appears in both lists -> highest RRF score
        b_entry = next(u for u in fused if u["id"] == "b")
        a_entry = next(u for u in fused if u["id"] == "a")
        assert b_entry["rrf_score"] > a_entry["rrf_score"]

        # b's score = 1/(60+2) + 1/(60+1) = 1/62 + 1/61
        assert b_entry["rrf_score"] == pytest.approx(1 / 61 + 1 / 62)

    def test_unit_in_both_lists(self) -> None:
        """Unit appearing in both lists gets summed score."""
        from loom.services.retrieval.search import rrf_fusion

        vector_results = [{"id": "a", "content": "A"}, {"id": "b", "content": "B"}]
        keyword_results = [{"id": "b", "content": "B"}, {"id": "c", "content": "C"}]

        fused = rrf_fusion(vector_results, keyword_results, k=60)

        b = next(u for u in fused if u["id"] == "b")
        # rank 2 in vector (1/(60+2)), rank 1 in keyword (1/(60+1))
        assert b["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)

        a = next(u for u in fused if u["id"] == "a")
        assert a["rrf_score"] == pytest.approx(1 / 61)  # rank 1 in vector only

        c = next(u for u in fused if u["id"] == "c")
        assert c["rrf_score"] == pytest.approx(1 / 62)  # rank 2 in keyword only

        assert b["rrf_score"] > a["rrf_score"]
        assert b["rrf_score"] > c["rrf_score"]

    def test_unit_in_one_list(self) -> None:
        """Unit in only one list gets score from that list only."""
        from loom.services.retrieval.search import rrf_fusion

        vector_results = [{"id": "a", "content": "A"}]
        keyword_results = [{"id": "b", "content": "B"}]

        fused = rrf_fusion(vector_results, keyword_results, k=60)

        assert len(fused) == 2
        a = next(u for u in fused if u["id"] == "a")
        b = next(u for u in fused if u["id"] == "b")
        assert a["rrf_score"] == pytest.approx(1 / 61)
        assert b["rrf_score"] == pytest.approx(1 / 61)

    def test_sorted_by_rrf_desc(self) -> None:
        """Results sorted by RRF score descending."""
        from loom.services.retrieval.search import rrf_fusion

        vector_results = [
            {"id": "a", "content": "A"},
            {"id": "b", "content": "B"},
            {"id": "c", "content": "C"},
        ]
        keyword_results = [
            {"id": "b", "content": "B"},
            {"id": "d", "content": "D"},
        ]

        fused = rrf_fusion(vector_results, keyword_results)
        scores = [u["rrf_score"] for u in fused]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_two_empty_lists(self) -> None:
        """Empty lists return empty list."""
        from loom.services.retrieval.search import rrf_fusion

        assert rrf_fusion([], []) == []

    def test_deduplicates_by_id(self) -> None:
        """Same unit appears once even if in both lists."""
        from loom.services.retrieval.search import rrf_fusion

        vector_results = [{"id": "a", "content": "A"}, {"id": "b", "content": "B"}]
        keyword_results = [{"id": "a", "content": "A"}]

        fused = rrf_fusion(vector_results, keyword_results)
        ids = [u["id"] for u in fused]
        assert ids.count("a") == 1
        assert len(fused) == 2  # a and b

    def test_single_list(self) -> None:
        """Single non-empty list returns that list ranked by RRF."""
        from loom.services.retrieval.search import rrf_fusion

        results = [
            {"id": "a", "content": "A"},
            {"id": "b", "content": "B"},
            {"id": "c", "content": "C"},
        ]

        fused = rrf_fusion(results, [], k=60)

        assert len(fused) == 3
        # RRF of single list: 1/(60+1), 1/(60+2), 1/(60+3)
        assert fused[0]["rrf_score"] == 1 / 61
        assert fused[1]["rrf_score"] == 1 / 62
        assert fused[2]["rrf_score"] == 1 / 63
        assert fused[0]["id"] == "a"
        assert fused[1]["id"] == "b"
        assert fused[2]["id"] == "c"


# ── Normalize RRF Scores Tests ──────────────────────────────────────────────────


class TestNormalizeRrfScores:
    """Tests for _normalize_rrf_scores — maps RRF scores to [0, 1]."""

    def test_normalizes_to_01_range(self) -> None:
        """Max score maps to 1.0, others proportionally."""
        from loom.services.retrieval.search import _normalize_rrf_scores

        units = [
            {"id": "a", "rrf_score": 0.05},
            {"id": "b", "rrf_score": 0.03},
            {"id": "c", "rrf_score": 0.01},
        ]

        result = _normalize_rrf_scores(units)

        assert result[0]["rrf_score"] == 1.0  # 0.05 / 0.05
        assert result[1]["rrf_score"] == 0.6  # 0.03 / 0.05
        assert result[2]["rrf_score"] == 0.2  # 0.01 / 0.05

    def test_all_zero_scores(self) -> None:
        """Division by zero prevented (all zeros stays zeros)."""
        from loom.services.retrieval.search import _normalize_rrf_scores

        units = [{"id": "a", "rrf_score": 0.0}, {"id": "b", "rrf_score": 0.0}]
        result = _normalize_rrf_scores(units)

        assert all(u["rrf_score"] == 0.0 for u in result)

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        from loom.services.retrieval.search import _normalize_rrf_scores

        assert _normalize_rrf_scores([]) == []

    def test_single_item(self) -> None:
        """Single item has score 1.0."""
        from loom.services.retrieval.search import _normalize_rrf_scores

        units = [{"id": "a", "rrf_score": 0.042}]
        result = _normalize_rrf_scores(units)

        assert result[0]["rrf_score"] == 1.0


# ── Compute Final Scores Tests ──────────────────────────────────────────────────


class TestComputeFinalScores:
    """Tests for compute_final_scores — applies the ranking formula."""

    def test_calls_compute_score_with_rrf(self) -> None:
        """Calls _compute_score using normalized RRF as ts_rank."""
        from loom.services.retrieval.search import compute_final_scores

        now = datetime.now(timezone.utc)
        units = [
            {
                "id": "a",
                "type": "decision",
                "trust_tier": "user",
                "content": "Test A",
                "created_at": now.isoformat(),
                "rrf_score": 0.8,
            },
        ]

        with patch(
            "loom.services.context.service._compute_score",
        ) as mock_compute:
            mock_compute.return_value = 0.75
            compute_final_scores(units)

            mock_compute.assert_called_once()
            _args, kwargs = mock_compute.call_args
            assert kwargs["ts_rank"] == 0.8
            assert kwargs["trust_tier"] == "user"
            assert kwargs["unit_type"] == "decision"

    def test_adds_relevance_score(self) -> None:
        """Each unit gets relevance_score field."""
        from loom.services.retrieval.search import compute_final_scores

        now = datetime.now(timezone.utc)
        units = [
            {
                "id": "a",
                "type": "decision",
                "trust_tier": "user",
                "content": "Test A",
                "created_at": now.isoformat(),
                "rrf_score": 1.0,
            },
            {
                "id": "b",
                "type": "summary",
                "trust_tier": "agent",
                "content": "Test B",
                "created_at": now.isoformat(),
                "rrf_score": 0.6,
            },
        ]

        scored = compute_final_scores(units)

        for u in scored:
            assert "relevance_score" in u
            assert isinstance(u["relevance_score"], float)

    def test_sorted_by_relevance_desc(self) -> None:
        """Results sorted descending by relevance_score."""
        from loom.services.retrieval.search import compute_final_scores

        now = datetime.now(timezone.utc)
        units = [
            {
                "id": "a",
                "type": "decision",
                "trust_tier": "user",
                "content": "A",
                "created_at": now.isoformat(),
                "rrf_score": 0.8,
            },
            {
                "id": "b",
                "type": "decision",
                "trust_tier": "agent",
                "content": "B",
                "created_at": now.isoformat(),
                "rrf_score": 0.6,
            },
            {
                "id": "c",
                "type": "decision",
                "trust_tier": "external_tool",
                "content": "C",
                "created_at": now.isoformat(),
                "rrf_score": 0.4,
            },
        ]

        scored = compute_final_scores(units)
        scores = [u["relevance_score"] for u in scored]

        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_summary_boost_applied(self) -> None:
        """Summary-type units get the +0.15 boost."""
        from loom.services.retrieval.search import compute_final_scores

        now = datetime.now(timezone.utc)
        units = [
            {
                "id": "a",
                "type": "summary",
                "trust_tier": "agent",
                "content": "Summary",
                "created_at": now.isoformat(),
                "rrf_score": 0.5,
            },
            {
                "id": "b",
                "type": "decision",
                "trust_tier": "agent",
                "content": "Decision",
                "created_at": now.isoformat(),
                "rrf_score": 0.5,
            },
        ]

        scored = compute_final_scores(units)

        summary_score = next(
            u["relevance_score"] for u in scored if u["id"] == "a"
        )
        decision_score = next(
            u["relevance_score"] for u in scored if u["id"] == "b"
        )
        assert summary_score == pytest.approx(decision_score + 0.15, rel=1e-4)


# ── Pack Results Tests ──────────────────────────────────────────────────────────


class TestPackResults:
    """Tests for pack_results — token-budget-aware packing."""

    def test_respects_budget(self) -> None:
        """total_tokens ≤ budget."""
        from loom.services.retrieval.search import pack_results

        units = [
            {"id": "a", "content": "Short", "relevance_score": 0.9},
            {"id": "b", "content": "Medium length content here", "relevance_score": 0.8},
        ]

        result = pack_results(units, budget=5)
        assert result["total_tokens"] <= 5
        assert result["truncated"] is False

    def test_truncates_last_unit(self) -> None:
        """Partial unit is truncated with truncated: true."""
        from loom.services.retrieval.search import pack_results

        units = [
            {"id": "a", "content": "AAAA", "relevance_score": 0.9},
            {
                "id": "b",
                "content": "BBBB content that exceeds available tokens",
                "relevance_score": 0.8,
            },
        ]

        result = pack_results(units, budget=2)

        assert result["truncated"] is True
        assert result["total_tokens"] == 2
        assert result["units"][1].get("truncated") is True

        # First unit (4 chars = 1 token) included fully
        assert result["units"][0]["id"] == "a"
        assert "truncated" not in result["units"][0]

    def test_all_units_fit(self) -> None:
        """All units included when budget is sufficient."""
        from loom.services.retrieval.search import pack_results

        units = [
            {"id": "a", "content": "A", "relevance_score": 0.9},
            {"id": "b", "content": "B", "relevance_score": 0.8},
        ]

        result = pack_results(units, budget=5)

        assert len(result["units"]) == 2
        assert result["truncated"] is False
        assert result["total_tokens"] == 2

    def test_zero_budget(self) -> None:
        """Empty list, 0 tokens when units is empty."""
        from loom.services.retrieval.search import pack_results

        result = pack_results([], budget=0)

        assert result["units"] == []
        assert result["total_tokens"] == 0
        assert result["truncated"] is False

    def test_budget_exhausted_skips_remaining(self) -> None:
        """Units beyond budget are skipped entirely."""
        from loom.services.retrieval.search import pack_results

        units = [
            {"id": "a", "content": "A", "relevance_score": 0.9},
            {"id": "b", "content": "BBB", "relevance_score": 0.8},
            {"id": "c", "content": "C", "relevance_score": 0.7},
        ]

        result = pack_results(units, budget=1)

        # Unit 'a' takes 1 token (ceil(1/4) = 1), exactly filling budget
        # Units 'b' and 'c' are skipped
        assert len(result["units"]) == 1
        assert result["units"][0]["id"] == "a"
        assert result["total_tokens"] == 1
        assert result["truncated"] is False


# ── Hybrid Search Tests ─────────────────────────────────────────────────────────


class TestHybridSearch:
    """Tests for hybrid_search orchestrator — vector + keyword with RRF."""

    @pytest.mark.asyncio
    async def test_full_hybrid_path(
        self,
        db_session,
        test_project,
        embedded_sample_units,
    ) -> None:
        """With query and units, returns combined results."""
        from loom.services.retrieval.search import hybrid_search

        result = await hybrid_search(
            db_session,
            test_project.id,
            "authentication security",
            budget=10000,
        )

        assert len(result["units"]) > 0
        assert result["degraded"] is False
        assert "total_tokens" in result
        assert result["total_tokens"] <= 10000
        assert "truncated" in result
        for unit in result["units"]:
            assert "relevance_score" in unit
            assert isinstance(unit["relevance_score"], float)

    @pytest.mark.asyncio
    async def test_scope_filter_propagated(
        self,
        db_session,
        test_project,
        test_agent,
        stub_embedder,
        embedded_sample_units,
    ) -> None:
        """scope_type_filter applied to both sub-queries."""
        from loom.services.retrieval.search import hybrid_search

        # Insert a summary unit with embedding
        summary_embedding = await stub_embedder.embed(
            "Project summary for authentication"
        )
        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, CAST(:embedding AS vector), :version, :created_at)
            """),
            {
                "id": uuid.uuid4(),
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "summary",
                "tier": "agent",
                "content": "Summary about authentication security decisions",
                "embedding": str(summary_embedding),
                "version": 1,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        # Query with scope_type_filter="summary"
        result = await hybrid_search(
            db_session,
            test_project.id,
            "authentication",
            scope_type_filter="summary",
            budget=10000,
        )

        assert len(result["units"]) > 0
        for unit in result["units"]:
            assert unit["type"] == "summary"

    @pytest.mark.asyncio
    async def test_degraded_fallback(
        self,
        db_session,
        test_project,
        embedded_sample_units,
    ) -> None:
        """When encode_query fails, returns keyword-only with degraded: true."""
        from loom.services.retrieval import search as search_module

        with patch.object(
            search_module,
            "encode_query",
            side_effect=Exception("Embedding API unavailable"),
        ):
            result = await search_module.hybrid_search(
                db_session,
                test_project.id,
                "bcrypt",
                budget=10000,
            )

        assert result["degraded"] is True
        # Keyword-only path should still return results
        assert len(result["units"]) > 0
        for unit in result["units"]:
            assert "relevance_score" in unit

    @pytest.mark.asyncio
    async def test_degraded_false_on_success(
        self,
        db_session,
        test_project,
        embedded_sample_units,
    ) -> None:
        """Full hybrid path has degraded: false."""
        from loom.services.retrieval.search import hybrid_search

        result = await hybrid_search(
            db_session,
            test_project.id,
            "authentication",
            budget=10000,
        )

        assert result["degraded"] is False

    @pytest.mark.asyncio
    async def test_empty_query_raises(
        self,
        db_session,
        test_project,
    ) -> None:
        """Raises ValueError for empty query (caller's responsibility)."""
        from loom.services.retrieval.search import hybrid_search

        with pytest.raises(ValueError, match="query"):
            await hybrid_search(
                db_session,
                test_project.id,
                "",
                budget=10000,
            )

    @pytest.mark.asyncio
    async def test_no_results(
        self,
        db_session,
        embedded_sample_units,
    ) -> None:
        """Returns empty result dict when nothing matches."""
        from loom.services.retrieval.search import hybrid_search

        # Use a non-existent project ID so both sub-queries return nothing
        fake_project_id = uuid.uuid4()

        result = await hybrid_search(
            db_session,
            fake_project_id,
            "authentication",
            budget=10000,
        )

        assert result["units"] == []
        assert result["total_tokens"] == 0
        assert result["truncated"] is False
        assert result["degraded"] is False
