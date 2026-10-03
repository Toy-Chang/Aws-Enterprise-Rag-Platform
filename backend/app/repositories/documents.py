"""Persistence for document metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document


class DocumentRepository:
    """Reads and writes document metadata through a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: Document) -> None:
        """Stage a new document for insertion."""
        self._session.add(document)

    def get(self, knowledge_base_id: str, document_id: str) -> Document | None:
        """Return a document scoped to its knowledge base, if it exists.

        Looking the document up through its knowledge base means an identifier from
        another knowledge base cannot be used to reach it.
        """
        return self._session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.knowledge_base_id == knowledge_base_id,
            )
        )

    def list_for_knowledge_base(self, knowledge_base_id: str) -> list[Document]:
        """Return the documents of a knowledge base, newest first."""
        statement = (
            select(Document)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .order_by(Document.created_at.desc(), Document.name)
        )
        return list(self._session.scalars(statement))

    def delete(self, document: Document) -> None:
        """Stage a document for removal."""
        self._session.delete(document)
