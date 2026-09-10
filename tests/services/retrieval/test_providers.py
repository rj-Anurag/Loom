"""Tests for LLM provider protocol and implementations (Phase 2.2 — A1).

These tests define the expected interface BEFORE implementation.
They will fail initially (Red phase)::

  - ``LLMProvider`` protocol does not exist yet
  - ``StubLLMProvider``, ``GroqLLMProvider`` do not exist yet
  - ``from_llm_config()`` factory does not exist yet
"""

from __future__ import annotations

import builtins

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

    async def test_groq_importable_without_groq_package(self) -> None:
        """GroqLLMProvider class is importable even when groq package is not installed.

        The ``import groq`` is done lazily inside ``summarize()``, so the class
        definition itself does not require the package.  Calling ``summarize()``
        with non-empty units triggers the lazy import and raises
        ``ModuleNotFoundError``.
        """
        from loom.services.retrieval.providers import GroqLLMProvider

        # Should not raise ImportError at class level
        provider = GroqLLMProvider(api_key="test-key")

        # Calling summarize() with non-empty input should trigger the
        # lazy ``import groq`` inside the method and raise ModuleNotFoundError
        with pytest.raises(ModuleNotFoundError):
            await provider.summarize(
                [
                    {
                        "id": "u1",
                        "content": "test",
                        "type": "message",
                        "trust_tier": "agent",
                        "created_at": "2026-01-01",
                        "agent_id": "a1",
                    }
                ]
            )


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
