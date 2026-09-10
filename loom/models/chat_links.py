import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from loom.db import Base


class ChatLink(Base):
    __tablename__ = "chat_links"
    __table_args__ = (
        UniqueConstraint("project_id", "chat_url", name="uq_chat_links_project_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    chat_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    platform: Mapped[str] = mapped_column(String, nullable=False, default="")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
