"""Ingestion use cases: a stored document in, embedded chunks out."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.ingestion import ChunkDraft, DocumentParseError, chunk_document, parse_document
from app.models import Chunk, Document, DocumentStatus
from app.rag import EmbeddingModel, VectorRecord, VectorStore
from app.repositories.chunks import ChunkRepository
from app.repositories.storage import DocumentStorage, DocumentStorageError

logger = get_logger(__name__)


class IngestionService:
    """Runs the ingestion pipeline for documents.

    The service opens its own sessions rather than receiving one, because it runs
    outside any request. The pipeline keeps one invariant the rest of the platform can
    rely on: a document is ``READY`` if and only if its chunks are stored and indexed.
    Every other outcome clears both, so nothing is ever retrieved through a document
    the API does not call ready.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        storage: DocumentStorage,
        embedder: EmbeddingModel,
        vector_store: VectorStore,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._embedder = embedder
        self._vector_store = vector_store
        self._chunk_size = settings.chunk_size_chars
        self._chunk_overlap = settings.chunk_overlap_chars
        self._batch_size = settings.ingestion_batch_size
        self._run_lock = threading.Lock()

    def run_pending(self, limit: int | None = None) -> int:
        """Ingest documents that are waiting, returning how many were processed."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")

        pending = self._pending(limit=self._batch_size if limit is None else limit)
        for knowledge_base_id, document_id in pending:
            self.run(knowledge_base_id, document_id)
        return len(pending)

    def run(self, knowledge_base_id: str, document_id: str) -> None:
        """Ingest one document, recording a failure instead of raising it.

        A run is triggered by the worker or by a caller that wants the result
        immediately, never by a request that is still holding a transaction, and it
        cannot report a problem by raising: there is no caller to catch it.
        """
        # Runs are serialised. The local adapters share one SQLite database, where
        # concurrent writers would only contend; the AWS consumer sets its own
        # concurrency.
        with self._run_lock:
            try:
                self._ingest(knowledge_base_id, document_id)
            except Exception as exc:
                logger.exception(
                    "document_ingestion_failed",
                    document_id=document_id,
                    error_type=type(exc).__name__,
                )
                try:
                    self._record_failure(document_id, _public_message(exc))
                except Exception:
                    logger.exception("document_failure_not_recorded", document_id=document_id)

    def recover_interrupted(self) -> int:
        """Return documents left mid-ingestion by a crash to the pending queue.

        Without this a document caught by a restart would sit in ``processing`` for
        ever, because nothing else looks at that status.
        """
        with session_scope(self._session_factory) as session:
            interrupted = list(
                session.scalars(
                    select(Document.id).where(Document.status == DocumentStatus.PROCESSING.value)
                )
            )
            if interrupted:
                session.execute(
                    update(Document)
                    .where(Document.id.in_(interrupted))
                    .values(status=DocumentStatus.PENDING.value)
                )
        return len(interrupted)

    def _pending(self, *, limit: int) -> list[tuple[str, str]]:
        """Return (knowledge base, document) pairs waiting to be ingested."""
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(Document.knowledge_base_id, Document.id)
                .where(Document.status == DocumentStatus.PENDING.value)
                .order_by(Document.created_at, Document.id)
                .limit(limit)
            ).all()
        return [(row[0], row[1]) for row in rows]

    def _ingest(self, knowledge_base_id: str, document_id: str) -> None:
        with session_scope(self._session_factory) as session:
            document = session.get(Document, document_id)
            if document is None or document.knowledge_base_id != knowledge_base_id:
                raise LookupError(f"document {document_id!r} does not exist")
            name = document.name
            storage_key = document.storage_key
            # Marking the document as processing is committed before the parse, so an
            # observer sees progress and a crash leaves an honest "processing" behind
            # rather than a document that silently never started.
            document.status = DocumentStatus.PROCESSING.value
            document.error_message = None

        content = self._storage.read(storage_key)
        parsed = parse_document(name, content)
        drafts = chunk_document(
            parsed, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap
        )
        if not drafts:
            raise DocumentParseError("no text could be extracted from the document")

        vectors = self._embedder.embed_documents([draft.content for draft in drafts])
        records = self._store_chunks(document_id, knowledge_base_id, drafts, vectors)

        # The index is updated only after the chunks are committed: a vector pointing
        # at a row nobody can read would break citation resolution.
        self._vector_store.delete_document(document_id)
        self._vector_store.upsert(records)

        logger.info(
            "document_ingested",
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            parser=parsed.parser,
            chunk_count=len(records),
            notes=list(parsed.notes),
        )

    def _store_chunks(
        self,
        document_id: str,
        knowledge_base_id: str,
        drafts: Sequence[ChunkDraft],
        vectors: Sequence[Sequence[float]],
    ) -> list[VectorRecord]:
        """Replace a document's chunks and mark it ready, in one transaction."""
        chunks = [
            Chunk(
                id=uuid4().hex,
                document_id=document_id,
                knowledge_base_id=knowledge_base_id,
                chunk_index=draft.index,
                content=draft.content,
                char_start=draft.char_start,
                char_end=draft.char_end,
                page_number=draft.page_number,
                heading_path=list(draft.heading_path),
                embedding=list(vector),
            )
            for draft, vector in zip(drafts, vectors, strict=True)
        ]

        with session_scope(self._session_factory) as session:
            repository = ChunkRepository(session)
            repository.delete_for_document(document_id)
            repository.add_all(chunks)
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.READY.value,
                    chunk_count=len(chunks),
                    error_message=None,
                )
            )

        return [
            VectorRecord(
                chunk_id=chunk.id,
                document_id=document_id,
                knowledge_base_id=knowledge_base_id,
                vector=tuple(chunk.embedding),
            )
            for chunk in chunks
        ]

    def _record_failure(self, document_id: str, message: str) -> None:
        """Mark a document failed and take it out of the index entirely."""
        with session_scope(self._session_factory) as session:
            ChunkRepository(session).delete_for_document(document_id)
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.FAILED.value,
                    chunk_count=0,
                    error_message=message,
                )
            )
        self._vector_store.delete_document(document_id)


def rebuild_vector_index(session_factory: sessionmaker[Session], vector_store: VectorStore) -> int:
    """Repopulate the in-memory index from the stored embeddings.

    The index is derived state, so it is rebuilt from the database at startup: a
    restart must not leave documents that claim to be ready while nothing can
    retrieve them. A real index does not need this step, and loading the whole corpus
    into memory is a deliberate local-only compromise.
    """
    with session_scope(session_factory) as session:
        chunks = ChunkRepository(session).list_indexable()
        records = [
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                knowledge_base_id=chunk.knowledge_base_id,
                vector=tuple(chunk.embedding),
            )
            for chunk in chunks
        ]

    vector_store.upsert(records)
    return len(records)


def _public_message(exc: Exception) -> str:
    """Describe a failure to API consumers without leaking internals."""
    if isinstance(exc, DocumentParseError):
        return str(exc)
    if isinstance(exc, DocumentStorageError):
        return "the stored content could not be read"
    return f"ingestion failed with an unexpected error ({type(exc).__name__})"
