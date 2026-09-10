"""Embedding providers for the async embedding pipeline.

Supports a pluggable ``EmbeddingProvider`` protocol with built-in ``StubProvider``
(deterministic random vectors — always available) and ``OpenAIProvider``
(requires ``openai`` package and ``OPENAI_API_KEY`` environment variable).
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Protocol, runtime_checkable

from loom.config import settings


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers.

    Every provider must accept a text string and return either a 1536-dimensional
    float vector or ``None`` (for empty / un-embeddable content).
    """

    async def embed(self, text: str) -> list[float] | None:
        """Compute an embedding vector for *text*.

        Returns ``None`` when the content is empty or cannot be embedded.
        """
        ...


# ── Stub Provider (always available) ────────────────────────────────────────────


class StubProvider:
    """Deterministic random embedding using a hash of the content as seed.

    Output is a unit vector (L2-normalised) of dimension 1536, suitable for
    cosine-similarity comparison.  Determinism ensures the same content always
    produces the same vector — useful for testing and stable retrieval.
    """

    DIMENSION = 1536

    async def embed(self, text: str) -> list[float] | None:
        if not text.strip():
            return None

        # Deterministic seed from content hash
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        raw = [rng.gauss(0, 1) for _ in range(self.DIMENSION)]

        # L2 normalise so the vector is unit length
        magnitude = math.sqrt(sum(v * v for v in raw))
        if magnitude == 0:
            return [0.0] * self.DIMENSION
        return [v / magnitude for v in raw]


# ── OpenAI Provider (optional) ─────────────────────────────────────────────────


class OpenAIProvider:
    """Embedding provider backed by the OpenAI Embeddings API.

    Requires the ``openai`` package and ``OPENAI_API_KEY`` to be set in the
    environment.  Uses ``text-embedding-3-small`` by default (1536 dimensions).
    """

    DIMENSION = 1536

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model

    async def embed(self, text: str) -> list[float] | None:
        if not text.strip():
            return None

        import openai

        client = openai.AsyncOpenAI()
        resp = await client.embeddings.create(
            model=self.model,
            input=text[:8191],  # OpenAI token limit ≈ 8191 input chars
        )
        vector = resp.data[0].embedding

        if len(vector) != self.DIMENSION:
            raise ValueError(
                f"Expected {self.DIMENSION}-dim embedding, "
                f"got {len(vector)} dim from model {self.model}"
            )
        return vector


# ── Local Provider (free, no API key) ────────────────────────────────────────────


class LocalProvider:
    """Free local embedding provider using `sentence-transformers`.

    Uses ``all-MiniLM-L6-v2`` (384-dimensional, ~80 MB download on first use).
    Runs entirely on CPU — no data ever leaves the machine.

    The model is loaded lazily on the first ``embed()`` call and cached
    for the lifetime of the process.
    """

    MODEL_DIMENSION = 384
    DIMENSION = 1536
    _model = None

    async def embed(self, text: str) -> list[float] | None:
        if not text.strip():
            return None

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Local embeddings require the optional dependency. "
                'Install it with: pip install "loom[local-embeddings]"'
            ) from exc

        if self._model is None:
            LocalProvider._model = SentenceTransformer("all-MiniLM-L6-v2")

        vector: list[float] = self._model.encode(text).tolist()  # type: ignore[union-attr]
        # The database vector column is 1536-dimensional. Zero-padding keeps
        # the local model usable without an incompatible schema migration.
        return vector + [0.0] * (self.DIMENSION - len(vector))


# ── Factory ────────────────────────────────────────────────────────────────────


# ── LLM Provider (Phase 2.2 — Hierarchical Summarization) ──────────────────────


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM summarization providers.

    Every provider must accept a list of context-unit dicts and return
    a condensed summary string preserving key decisions and state.
    """

    async def summarize(self, context_units: list[dict[str, Any]]) -> str:
        """Generate a summary of the given context units.

        Parameters
        ----------
        context_units : list[dict]
            Each dict has at least ``id``, ``content``, ``type``,
            ``trust_tier``, ``created_at``, and ``agent_id`` keys.

        Returns
        -------
        str
            The condensed summary text.
        """
        ...


class StubLLMProvider:
    """Deterministic stub summarizer for tests.

    Returns a concatenation of the unit contents prefixed with
    a header, truncated at 1000 chars.  Always available — no
    external dependencies.
    """

    async def summarize(self, context_units: list[dict[str, Any]]) -> str:
        if not context_units:
            return ""
        header = f"Stub summary of {len(context_units)} units:\n"
        body = "; ".join(u.get("content", "")[:200] for u in context_units)
        return (header + body)[:1000]


class GroqLLMProvider:
    """LLM provider backed by the Groq API.

    Requires the ``groq`` package and ``GROQ_API_KEY`` environment
    variable.  Uses ``mixtral-8x7b-32768`` by default for fast
    summarization with large context windows.
    """

    _SUMMARY_PROMPT = (
        "You are a technical summarizer. Condense the following "
        "context units into a concise summary preserving key "
        "decisions, findings, and state. Omit low-signal details.\n\n"
        "# Context Units\n\n{units_text}"
    )

    MAX_INPUT_CHARS = 30000

    def __init__(
        self,
        model: str = "mixtral-8x7b-32768",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key

    async def summarize(self, context_units: list[dict[str, Any]]) -> str:
        if not context_units:
            return ""
        units_text = self._format_units(context_units)
        prompt = self._SUMMARY_PROMPT.format(units_text=units_text)

        import groq as groq_client

        client = groq_client.AsyncGroq(api_key=self._api_key)
        resp = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt[:self.MAX_INPUT_CHARS]}],
            temperature=0.3,
            max_tokens=1024,
        )
        return resp.choices[0].message.content or ""

    def _format_units(self, units: list[dict[str, Any]]) -> str:
        lines = []
        for i, u in enumerate(units, 1):
            # Isolate each unit's content behind XML-like boundary markers
            # to mitigate prompt-injection from unit content.
            content = (u.get("content", "") or "")[:4000]
            lines.append(
                f'<unit index="{i}" type="{u.get("type", "unknown")}" '
                f'tier="{u.get("trust_tier", "agent")}">\n'
                f"{content}\n"
                f"</unit>"
            )
        return "\n\n".join(lines)


def from_llm_config() -> LLMProvider:
    """Build an LLM provider based on ``settings.summarization_provider``.

    ``"stub"`` (default) → :class:`StubLLMProvider`
    ``"groq"``           → :class:`GroqLLMProvider`

    Raises
    ------
    ValueError
        If the provider name is not recognized.
    """
    provider_name = settings.summarization_provider.lower()
    if provider_name == "groq":
        return GroqLLMProvider(api_key=settings.groq_api_key or None)
    if provider_name == "stub":
        return StubLLMProvider()
    msg = f"Unrecognised summarization provider: {settings.summarization_provider!r}"
    raise ValueError(msg)


# ── Factory ────────────────────────────────────────────────────────────────────


def from_config() -> EmbeddingProvider:
    """Build an embedding provider based on ``settings.embedding_provider``.

    ``"stub"`` (default) → :class:`StubProvider`
    ``"openai"``         → :class:`OpenAIProvider`
    ``"local"``          → :class:`LocalProvider`
    ``"sentence_transformers"`` → :class:`LocalProvider` (legacy alias)
    """
    provider_name = settings.embedding_provider.lower()
    if provider_name == "openai":
        return OpenAIProvider()
    if provider_name in {"local", "sentence_transformers"}:
        return LocalProvider()
    if provider_name == "stub":
        return StubProvider()
    msg = f"Unrecognised embedding provider: {settings.embedding_provider!r}"
    raise ValueError(msg)
