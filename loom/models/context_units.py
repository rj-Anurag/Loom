from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from loom.db import Base


class ContextUnitType(str, enum.Enum):
    message = "message"
    decision = "decision"
    artifact_ref = "artifact_ref"
    task_result = "task_result"
    summary = "summary"


class TrustTier(str, enum.Enum):
    user = "user"
    agent = "agent"
    external_tool = "external_tool"


class ContextUnit(Base):
    __tablename__ = "context_units"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    client_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False
    )
    type: Mapped[ContextUnitType] = mapped_column(
        Enum(ContextUnitType, name="context_unit_type"),
        nullable=False,
    )
    trust_tier: Mapped[TrustTier] = mapped_column(
        Enum(TrustTier, name="trust_tier"),
        nullable=False,
        default=TrustTier.agent,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship()  # noqa: F821
