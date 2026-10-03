"""Knowledge base use cases."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import KnowledgeBase
from app.repositories.documents import DocumentRepository
from app.repositories.knowledge_bases import KnowledgeBaseRepository
from app.repositories.storage import DocumentStorage
from app.schemas.knowledge_base import KnowledgeBaseCreate
from app.services.documents import DocumentService


class KnowledgeBaseService:
    """Creates, reads and removes knowledge bases."""

    def __init__(self, session: Session, storage: DocumentStorage) -> None:
        self._session = session
        self._knowledge_bases = KnowledgeBaseRepository(session)
        self._documents = DocumentRepository(session)
        self._document_service = DocumentService(session, storage)

    def create(self, payload: KnowledgeBaseCreate) -> KnowledgeBase:
        """Create a knowledge base.

        Names are unique across the platform. Scoping them per tenant arrives with
        authentication; until then a single namespace is the honest model.
        """
        if self._knowledge_bases.get_by_name(payload.name) is not None:
            raise ConflictError(
                "A knowledge base with this name already exists.",
                details={"field": "name"},
            )

        knowledge_base = KnowledgeBase(
            id=uuid4().hex,
            name=payload.name,
            description=payload.description,
        )
        self._knowledge_bases.add(knowledge_base)
        self._session.flush()
        return knowledge_base

    def list(self) -> list[KnowledgeBase]:
        """Return every knowledge base."""
        return self._knowledge_bases.list()

    def get(self, knowledge_base_id: str) -> KnowledgeBase:
        """Return one knowledge base."""
        knowledge_base = self._knowledge_bases.get(knowledge_base_id)
        if knowledge_base is None:
            raise NotFoundError(f"Knowledge base {knowledge_base_id!r} was not found.")
        return knowledge_base

    def delete(self, knowledge_base_id: str) -> None:
        """Remove a knowledge base together with its documents."""
        knowledge_base = self.get(knowledge_base_id)
        for document in self._documents.list_for_knowledge_base(knowledge_base_id):
            self._document_service.remove(document)
        self._knowledge_bases.delete(knowledge_base)
