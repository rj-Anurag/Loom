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
