"""Tests for LLM provider protocol and implementations (Phase 2.2 — A1).

These tests define the expected interface BEFORE implementation.
They will fail initially (Red phase)::

  - ``LLMProvider`` protocol does not exist yet
  - ``StubLLMProvider``, ``GroqLLMProvider`` do not exist yet
  - ``from_llm_config()`` factory does not exist yet
"""

from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


# ── Tests ────────────────────────────────────────────────────────────────────


class TestLLMProviderProtocol:
    """LLMProvider must be a Protocol with an ``async summarize`` method."""

    async def test_stub_returns_empty_for_empty_list(self) -> None:
        """StubLLMProvider.summarize([]) returns empty string."""
        from loom.services.retrieval.providers import StubLLMProvider

        provider = StubLLMProvider()
        result = await provider.summarize([])
        assert result == ""

    async def test_stub_concatenates_contents(self) -> None:
        """StubLLMProvider concatenates unit contents with a header."""
        from loom.services.retrieval.providers import StubLLMProvider

        provider = StubLLMProvider()
        units: list[dict] = [
            {
                "id": "u1",
                "content": "First decision",
                "type": "decision",
                "trust_tier": "agent",
                "created_at": "2026-01-01",
                "agent_id": "a1",
            },
            {
                "id": "u2",
                "content": "Second finding",
                "type": "message",
                "trust_tier": "user",
                "created_at": "2026-01-01",
                "agent_id": "a2",
            },
        ]
        result = await provider.summarize(units)
        assert "Stub summary of 2 units" in result
        assert "First decision" in result
        assert "Second finding" in result

    async def test_stub_truncates_at_1000_chars(self) -> None:
        """StubLLMProvider truncates result to 1000 characters."""
        from loom.services.retrieval.providers import StubLLMProvider

        provider = StubLLMProvider()
        units: list[dict] = [
            {
                "id": f"u{i}",
                "content": "A" * 300,
                "type": "message",
                "trust_tier": "agent",
                "created_at": "2026-01-01",
                "agent_id": "a1",
            }
            for i in range(10)
        ]
        result = await provider.summarize(units)
        assert len(result) <= 1000

    async def test_from_llm_config_stub(self) -> None:
        """from_llm_config() returns StubLLMProvider when provider is 'stub'."""
        import loom.config
        from loom.services.retrieval.providers import StubLLMProvider, from_llm_config

        original = loom.config.settings.summarization_provider
        loom.config.settings.summarization_provider = "stub"
        try:
            provider = from_llm_config()
            assert isinstance(provider, StubLLMProvider)
        finally:
            loom.config.settings.summarization_provider = original

    async def test_from_llm_config_groq(self) -> None:
        """from_llm_config() returns GroqLLMProvider when provider is 'groq'."""
        import loom.config
        from loom.services.retrieval.providers import GroqLLMProvider, from_llm_config

        original = loom.config.settings.summarization_provider
        loom.config.settings.summarization_provider = "groq"
        try:
            provider = from_llm_config()
            assert isinstance(provider, GroqLLMProvider)
        finally:
            loom.config.settings.summarization_provider = original

    async def test_groq_uses_installed_openai_client_and_supported_model(self, monkeypatch) -> None:
        """Summarization works through the installed OpenAI client without a Groq SDK."""
        import openai

        from loom.services.retrieval.providers import GroqLLMProvider

        captured = {}

        async def complete(**kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="[1] A fact")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        def client(**kwargs):
            captured.update(kwargs)
            completions = SimpleNamespace(create=complete)
            return SimpleNamespace(chat=SimpleNamespace(completions=completions))

        monkeypatch.setattr(openai, "AsyncOpenAI", client)
        provider = GroqLLMProvider(api_key="test-key")
        result = await provider.summarize([{"content": "[1] A fact", "type": "message"}])
        assert result == "[1] A fact"
        assert captured["base_url"] == "https://api.groq.com/openai/v1"
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "openai/gpt-oss-120b"
        assert captured["reasoning_effort"] == "low"
        assert captured["max_tokens"] == 2048
        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][1]["role"] == "user"
        assert "[1] A fact" in captured["messages"][1]["content"]

        await provider.summarize(
            [
                {
                    "content": "[1] A fact",
                    "type": "message",
                    "output_format": "project_summary",
                }
            ]
        )
        assert "## Overview" in captured["messages"][0]["content"]
        assert "Do not include a Sources section" in captured["messages"][0]["content"]

        from loom.services.retrieval.providers import XAILLMProvider

        captured.clear()
        await XAILLMProvider(api_key="xai-test").summarize(
            [{"content": "[1] A fact", "type": "message"}]
        )
        assert captured["base_url"] == "https://api.x.ai/v1"
        assert captured["model"] == "grok-4.3"
        assert "reasoning_effort" not in captured

    async def test_groq_requires_its_own_api_key(self) -> None:
        from loom.services.retrieval.providers import GroqLLMProvider

        with pytest.raises(ValueError, match="GROQ_API_KEY_NOT_CONFIGURED"):
            await GroqLLMProvider(api_key=None).summarize([{"content": "A fact"}])

    async def test_auto_uses_grok_key_before_groq_key(self, monkeypatch) -> None:
        import loom.config
        from loom.services.retrieval.providers import (
            GroqLLMProvider,
            StubLLMProvider,
            XAILLMProvider,
            from_llm_config,
        )

        monkeypatch.setattr(loom.config.settings, "summarization_provider", "auto")
        monkeypatch.setattr(loom.config.settings, "xai_api_key", "xai-test")
        monkeypatch.setattr(loom.config.settings, "groq_api_key", "groq-test")
        provider = from_llm_config()
        assert type(provider) is XAILLMProvider
        assert provider.BASE_URL == "https://api.x.ai/v1"
        assert provider.model == "grok-4.3"

        monkeypatch.setattr(loom.config.settings, "xai_api_key", "")
        assert type(from_llm_config()) is GroqLLMProvider
        monkeypatch.setattr(loom.config.settings, "groq_api_key", "")
        assert type(from_llm_config()) is StubLLMProvider


class TestLLMProviderRuntimeCheckable:
    """LLMProvider should be runtime-checkable via isinstance()."""

    async def test_stub_is_llm_provider(self) -> None:
        """isinstance(StubLLMProvider(), LLMProvider) is True."""
        from loom.services.retrieval.providers import LLMProvider, StubLLMProvider

        assert isinstance(StubLLMProvider(), LLMProvider)


class TestEmbeddingProviderConfiguration:
    """Embedding provider configuration must never fail open to the stub."""

    async def test_local_aliases_select_local_provider(self) -> None:
        import loom.config
        from loom.services.retrieval.providers import LocalProvider, from_config

        original = loom.config.settings.embedding_provider
        try:
            for provider_name in ("local", "sentence_transformers"):
                loom.config.settings.embedding_provider = provider_name
                assert isinstance(from_config(), LocalProvider)
        finally:
            loom.config.settings.embedding_provider = original

    async def test_unknown_embedding_provider_is_rejected(self) -> None:
        import loom.config
        from loom.services.retrieval.providers import from_config

        original = loom.config.settings.embedding_provider
        loom.config.settings.embedding_provider = "typo-provider"
        try:
            with pytest.raises(ValueError, match="Unrecognised embedding provider"):
                from_config()
        finally:
            loom.config.settings.embedding_provider = original

    async def test_local_provider_explains_missing_optional_dependency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loom.services.retrieval.providers import LocalProvider

        real_import = builtins.__import__

        def reject_sentence_transformers(name: str, *args: object, **kwargs: object) -> object:
            if name == "sentence_transformers":
                raise ModuleNotFoundError("No module named 'sentence_transformers'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", reject_sentence_transformers)

        with pytest.raises(RuntimeError, match=r"pip install .*local-embeddings"):
            await LocalProvider().embed("context to embed")
