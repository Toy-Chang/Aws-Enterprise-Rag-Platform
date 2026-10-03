"""Document use cases."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnsupportedMediaTypeError
from app.core.logging import get_logger
from app.models import Document, DocumentStatus
from app.repositories.documents import DocumentRepository
from app.repositories.knowledge_bases import KnowledgeBaseRepository
from app.repositories.storage import DocumentStorage, DocumentStorageError

logger = get_logger(__name__)

#: Document formats the ingestion pipeline will be able to parse.
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".md", ".markdown", ".txt"})


class DocumentService:
    """Registers, lists and removes the documents of a knowledge base."""

    def __init__(self, session: Session, storage: DocumentStorage) -> None:
        self._session = session
        self._storage = storage
        self._documents = DocumentRepository(session)
        self._knowledge_bases = KnowledgeBaseRepository(session)

    def upload(
        self,
        knowledge_base_id: str,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> Document:
        """Store uploaded content and register its metadata.

        The content is written before the metadata because metadata is what other
        requests read: content without a row is invisible and reclaimable, whereas a
        row without content is a broken reference. The two writes are not a single
        transaction, so a failure between them leaves content behind in the store.
        """
        self.require_knowledge_base(knowledge_base_id)

        name = Path(filename).name if filename else ""
        if not name or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise UnsupportedMediaTypeError(
                "Only PDF, Markdown and plain-text documents are supported.",
                details={"supported_extensions": sorted(SUPPORTED_EXTENSIONS)},
            )

        document_id = uuid4().hex
        storage_key = f"{knowledge_base_id}/{document_id}"
        self._storage.save(storage_key, content)

        document = Document(
            id=document_id,
            knowledge_base_id=knowledge_base_id,
            name=name,
            content_type=content_type,
            size_bytes=len(content),
            status=DocumentStatus.PENDING.value,
            storage_key=storage_key,
            version=1,
        )
        self._documents.add(document)
        self._session.flush()
        return document

    def list_for_knowledge_base(self, knowledge_base_id: str) -> list[Document]:
        """Return the documents of a knowledge base."""
        self.require_knowledge_base(knowledge_base_id)
        return self._documents.list_for_knowledge_base(knowledge_base_id)

    def get(self, knowledge_base_id: str, document_id: str) -> Document:
        """Return one document of a knowledge base."""
        self.require_knowledge_base(knowledge_base_id)
        document = self._documents.get(knowledge_base_id, document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id!r} was not found.")
        return document

    def delete(self, knowledge_base_id: str, document_id: str) -> None:
        """Remove a document from a knowledge base."""
        self.remove(self.get(knowledge_base_id, document_id))

    def remove(self, document: Document) -> None:
        """Remove a document's content and its metadata.

        Storage failures are logged rather than raised: metadata is the source of
        truth, so a document whose content cannot be removed is still deleted
        instead of leaving a row that points at content nobody can read. Content
        left behind by a failed removal is reclaimed out of band.
        """
        try:
            self._storage.delete(document.storage_key)
        except DocumentStorageError:
            logger.warning("document_content_not_removed", storage_key=document.storage_key)
        self._documents.delete(document)

    def require_knowledge_base(self, knowledge_base_id: str) -> None:
        """Raise :class:`~app.core.errors.NotFoundError` if the knowledge base is absent."""
        if self._knowledge_bases.get(knowledge_base_id) is None:
            raise NotFoundError(f"Knowledge base {knowledge_base_id!r} was not found.")
