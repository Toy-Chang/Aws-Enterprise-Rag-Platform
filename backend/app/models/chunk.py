"""Chunk model.

Chunks are durable. The vector index is a derived structure that can be rebuilt from
this table, which is why the embedding vector is stored alongside the text: a restart
must not leave documents marked ready that nothing can retrieve.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base):
    """One embedded passage of a document."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(nullable=False)
    char_end: Mapped[int] = mapped_column(nullable=False)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Stored as JSON text. A native vector column (pgvector) or an external index
    # replaces this in the AWS deployment; keeping it here makes the in-memory index
    # rebuildable without re-embedding the corpus.
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)

    # Chunks are rewritten as a whole when a document is re-ingested, so they only
    # carry a creation timestamp.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")
