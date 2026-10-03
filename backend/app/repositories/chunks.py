"""Persistence for document chunks."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, DocumentStatus


class ChunkRepository:
    """Reads and writes document chunks through a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, chunks: Sequence[Chunk]) -> None:
        """Stage a batch of chunks for insertion."""
        self._session.add_all(list(chunks))

    def delete_for_document(self, document_id: str) -> None:
        """Remove every chunk of a document."""
        self._session.execute(delete(Chunk).where(Chunk.document_id == document_id))

    def get(self, chunk_id: str) -> Chunk | None:
        """Return a chunk by identifier."""
        return self._session.get(Chunk, chunk_id)

    def list_for_document(self, document_id: str) -> list[Chunk]:
        """Return a document's chunks in reading order."""
        statement = (
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
        )
        return list(self._session.scalars(statement))

    def list_indexable(self) -> list[Chunk]:
        """Return the chunks of every document that is ready to be retrieved.

        Only ``READY`` documents are indexed. A document left mid-ingestion by a
        crash therefore stays out of the index instead of being searchable in a state
        the API never reports as usable.
        """
        statement = (
            select(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.status == DocumentStatus.READY.value)
            .order_by(Chunk.document_id, Chunk.chunk_index)
        )
        return list(self._session.scalars(statement))

    def list_with_document_names(self, chunk_ids: Sequence[str]) -> list[tuple[Chunk, str]]:
        """Return the given chunks paired with the name of their document.

        Retrieval resolves search results through this method: the index holds
        identifiers and vectors only, so the text a citation quotes, and the document it
        belongs to, are read here.
        """
        if not chunk_ids:
            return []

        statement = (
            select(Chunk, Document.name)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(list(chunk_ids)))
        )
        return [(chunk, name) for chunk, name in self._session.execute(statement)]
