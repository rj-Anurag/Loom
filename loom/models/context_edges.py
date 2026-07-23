import enum
import uuid

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from loom.db import Base


class EdgeRelation(str, enum.Enum):
    derived_from = "derived_from"
    supersedes = "supersedes"
    references = "references"
    merged_from = "merged_from"


class ContextEdge(Base):
    __tablename__ = "context_edges"

    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_units.id"), primary_key=True
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_units.id"), primary_key=True
    )
    relation: Mapped[EdgeRelation] = mapped_column(
        Enum(EdgeRelation, name="edge_relation"), primary_key=True
    )
