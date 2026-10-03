"""Document metadata model."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.knowledge_base import KnowledgeBase


class DocumentStatus(enum.StrEnum):
    """Lifecycle of a stored document.

    Upload sets ``PENDING``; the ingestion pipeline moves a document to
    ``PROCESSING`` while it parses, chunks and embeds, and finishes at ``READY`` or
    ``FAILED``. ``READY`` is the only status that guarantees the document is
    searchable, and ``FAILED`` carries the reason in ``error_message``.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base, TimestampMixin):
    """Metadata for a document whose content lives in the document store."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=DocumentStatus.PENDING.value, nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
