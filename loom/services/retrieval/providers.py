"""Embedding providers for the async embedding pipeline.

Supports a pluggable ``EmbeddingProvider`` protocol with built-in ``StubProvider``
(deterministic random vectors — always available) and ``OpenAIProvider``
(requires ``openai`` package and ``OPENAI_API_KEY`` environment variable).
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Protocol, runtime_checkable

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


# ── Factory ────────────────────────────────────────────────────────────────────


def from_config() -> EmbeddingProvider:
    """Build an embedding provider based on ``settings.embedding_provider``.

    ``"stub"`` (default) → :class:`StubProvider`
    ``"openai"``         → :class:`OpenAIProvider`
    """
    provider_name = settings.embedding_provider.lower()
    if provider_name == "openai":
        return OpenAIProvider()
    return StubProvider()
