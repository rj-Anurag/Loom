from loom.models.context_units import ContextUnit
from loom.services.retrieval.providers import LocalProvider, StubProvider


def test_context_unit_embedding_column_matches_shared_dimension() -> None:
    embedding_column = ContextUnit.__table__.c.embedding.type
    assert embedding_column.dim == 1536


def test_embedding_providers_use_shared_dimension() -> None:
    assert StubProvider.DIMENSION == 1536
    assert LocalProvider.DIMENSION == 1536
