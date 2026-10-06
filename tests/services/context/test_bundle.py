"""Bundle ranking, fallback, and budget behavior without external services."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from loom.services.context import bundle


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def scalars(self):
        return iter(self.rows)


def test_query_ignores_example_marker_words_and_omits_missing_provenance() -> None:
    assert bundle._terms("LOOM_E2E_<unique> Aurora") == ["aurora"]
    unit = SimpleNamespace(
        id=uuid.uuid4(),
        type=SimpleNamespace(value="message"),
        content="Aurora is teal",
        source_type="codex_cli",
        source_url="https://example.test/irrelevant",
        source_session_id="session-one",
        occurred_at=datetime.now(UTC),
    )
    item = bundle._unit_dict(unit, 1)
    assert "source_url" not in item
    assert item["source_session_id"] == "session-one"
    unit.source_type = "browser_chat"
    unit.source_url = "https://example.test/chat"
    unit.source_session_id = "not-shown-for-browser"
    item = bundle._unit_dict(unit, 2)
    assert item["source_url"] == "https://example.test/chat"
    assert "source_session_id" not in item


@pytest.mark.asyncio
async def test_unmatched_prompt_returns_no_history(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    session = SimpleNamespace(execute=AsyncMock(return_value=Rows([])))
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="unicorn spacecraft"
    )
    assert result["evidence"] == []
    assert result["brief"] == ""


@pytest.mark.asyncio
async def test_provider_failure_keeps_cited_evidence_within_budget(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    monkeypatch.setattr(bundle.settings, "summarization_provider", "groq")

    class FailingProvider:
        async def summarize(self, _units):
            raise RuntimeError("unavailable")

    monkeypatch.setattr(bundle, "from_llm_config", lambda: FailingProvider())
    unit = SimpleNamespace(
        id=uuid.uuid4(),
        type=SimpleNamespace(value="decision"),
        content="Login tokens expire after one hour " * 20,
        source_type="mcp_agent",
        source_url=None,
        source_session_id=None,
        occurred_at=datetime.now(UTC),
        context_metadata={},
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Rows([(unit, 0.8)]),
                Rows([]),
            ]
        )
    )
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="login token expiry", budget=100
    )
    assert result["evidence"]
    assert "[1]" in result["brief"]
    assert result["total_tokens"] <= 100
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_provider_brief_cites_the_original_unit(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    monkeypatch.setattr(bundle.settings, "summarization_provider", "groq")
    received = []

    class Provider:
        async def summarize(self, units):
            received.extend(units)
            return "The expiry was set to one hour."

    monkeypatch.setattr(bundle, "from_llm_config", lambda: Provider())
    unit = SimpleNamespace(
        id=uuid.uuid4(),
        type=SimpleNamespace(value="decision"),
        content="Login expiry is one hour",
        source_type="mcp_agent",
        source_url=None,
        source_session_id=None,
        occurred_at=datetime.now(UTC),
        context_metadata={},
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Rows([(unit, 1.0)]),
                Rows([]),
            ]
        )
    )
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="login expiry", budget=500
    )
    assert "[1]" in result["brief"]
    assert result["evidence"][0]["id"] == str(unit.id)
    assert received[0]["content"].startswith("[1]")


@pytest.mark.asyncio
async def test_bundle_excludes_unrelated_neighbors_and_skips_vector_noise(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    monkeypatch.setattr(bundle.settings, "embedding_provider", "openai")
    vector = AsyncMock()
    monkeypatch.setattr(bundle, "vector_search", vector)
    now = datetime.now(UTC)

    def unit(content):
        return SimpleNamespace(
            id=uuid.uuid4(),
            type=SimpleNamespace(value="message"),
            content=content,
            source_type="codex_cli",
            source_url=None,
            source_session_id="session-one",
            occurred_at=now,
            context_metadata={},
        )

    related = unit("Aurora is teal")
    unrelated = unit("The LangChain thread configuration uses an in-memory saver")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Rows([(related, 0.5)]),
                Rows([unrelated, related]),
                Rows([related, unrelated]),
                Rows([]),
            ]
        )
    )
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="LOOM_E2E_<unique> Aurora"
    )
    assert [item["id"] for item in result["evidence"]] == [str(related.id)]
    vector.assert_not_awaited()


@pytest.mark.asyncio
async def test_weak_semantic_match_does_not_supply_unrelated_history(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    monkeypatch.setattr(bundle.settings, "embedding_provider", "openai")
    monkeypatch.setattr(bundle, "encode_query", AsyncMock(return_value=[0.1]))
    monkeypatch.setattr(
        bundle,
        "vector_search",
        AsyncMock(return_value=[{"id": str(uuid.uuid4()), "vector_score": 0.6}]),
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=Rows([])))
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="Aurora retry limit"
    )
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_factual_match_precedes_a_long_command_echo(monkeypatch) -> None:
    monkeypatch.setattr(bundle, "_validate_context_reader", AsyncMock())
    now = datetime.now(UTC)

    def unit(content, source_type, source_url=None, source_session_id=None):
        return SimpleNamespace(
            id=uuid.uuid4(),
            type=SimpleNamespace(value="message"),
            content=content,
            source_type=source_type,
            source_url=source_url,
            source_session_id=source_session_id,
            occurred_at=now,
            context_metadata={},
        )

    command = unit(
        'loom context "LOOM_E2E_<unique> Aurora" --rich --json '
        "HTTP Request: POST and an unrelated setup explanation",
        "codex_cli",
        source_session_id="session-one",
    )
    fact = unit(
        "User: Aurora is teal; its retry limit is seven.",
        "browser_chat",
        source_url="https://example.test/chat",
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Rows([(command, 0.1), (fact, 0.1)]),
                Rows([fact]),
                Rows([fact]),
                Rows([command]),
                Rows([command]),
                Rows([]),
            ]
        )
    )
    result = await bundle.build_context_bundle(
        session, uuid.uuid4(), uuid.uuid4(), prompt="LOOM_E2E_<unique> Aurora"
    )
    assert result["evidence"][0]["id"] == str(fact.id)
    assert "Aurora is teal" in result["brief"].splitlines()[1]
