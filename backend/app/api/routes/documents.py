"""Document endpoints, nested under a knowledge base."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    DocumentQueueDep,
    EditorDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    VectorStoreDep,
)
from app.core.errors import PayloadTooLargeError
from app.repositories.queue import DocumentQueue, IngestionMessage
from app.schemas.chunk import ChunkRead
from app.schemas.document import DocumentRead
from app.services.documents import DocumentService

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}/documents", tags=["documents"])

_READ_CHUNK_BYTES = 1024 * 1024


def _publish_ingestion_work(
    session: Session,
    queue: DocumentQueue,
    *,
    knowledge_base_id: str,
    document_id: str,
) -> None:
    """Publish the document for ingestion, after committing the row it refers to.

    The commit comes first on purpose. Publishing inside the request's transaction lets a
    consumer receive the message before the document is visible, and for a reprocess that
    is not self-correcting: the consumer would see the document's *previous* terminal
    state and treat the message as done, leaving the new work unqueued. Committing first
    means anything a consumer sees is what the database actually holds.
    """
    session.commit()
    queue.enqueue(IngestionMessage(knowledge_base_id=knowledge_base_id, document_id=document_id))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
def upload_document(
    knowledge_base_id: str,
    file: Annotated[UploadFile, File(description="A PDF, Markdown or plain-text document.")],
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
    queue: DocumentQueueDep,
    settings: SettingsDep,
    _editor: EditorDep,
) -> DocumentRead:
    """Store a document in a knowledge base and queue it for ingestion.

    The response reports the document as ``pending``, because parsing, chunking and
    embedding take far longer than a client should wait. The ingestion worker picks
    it up and settles it at ``ready`` or ``failed``; polling this endpoint is how a
    caller watches that happen, and ``error_message`` carries the reason on failure.

    A deployment that publishes to a queue can fail here: the work is not queued, so
    the request answers ``502`` and the document stays ``pending`` until it is
    reprocessed. That is reported rather than swallowed, because a caller told the
    upload succeeded would have no way to learn that nothing will ingest it.
    """
    content = _read_within_limit(file, settings.max_upload_size_bytes)
    document = DocumentService(session, storage, vector_store).upload(
        knowledge_base_id,
        filename=file.filename,
        content_type=file.content_type,
        content=content,
    )
    _publish_ingestion_work(
        session, queue, knowledge_base_id=knowledge_base_id, document_id=document.id
    )
    return DocumentRead.model_validate(document)


@router.get("", summary="List the documents of a knowledge base")
def list_documents(
    knowledge_base_id: str,
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
) -> list[DocumentRead]:
    """Return the documents of a knowledge base, newest first."""
    documents = DocumentService(session, storage, vector_store).list_for_knowledge_base(
        knowledge_base_id
    )
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", summary="Get document metadata")
def get_document(
    knowledge_base_id: str,
    document_id: str,
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
) -> DocumentRead:
    """Return the metadata of one document, including its processing status."""
    document = DocumentService(session, storage, vector_store).get(knowledge_base_id, document_id)
    return DocumentRead.model_validate(document)


@router.get("/{document_id}/chunks", summary="List the indexed passages of a document")
def list_document_chunks(
    knowledge_base_id: str,
    document_id: str,
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
) -> list[ChunkRead]:
    """Return the passages the ingestion pipeline produced, in reading order.

    The list is empty until ingestion succeeds, which makes it the direct view of
    what retrieval will be able to cite.
    """
    chunks = DocumentService(session, storage, vector_store).list_chunks(
        knowledge_base_id, document_id
    )
    return [ChunkRead.model_validate(chunk) for chunk in chunks]


@router.post(
    "/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run ingestion for a document",
)
def reprocess_document(
    knowledge_base_id: str,
    document_id: str,
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
    queue: DocumentQueueDep,
    _editor: EditorDep,
) -> DocumentRead:
    """Discard the document's indexed passages and queue it for ingestion again.

    This is the recovery path for a document that failed to parse, and the way to
    re-index after the chunking configuration changes. The response reports
    ``pending``; the worker does the rest.
    """
    document = DocumentService(session, storage, vector_store).reprocess(
        knowledge_base_id, document_id
    )
    _publish_ingestion_work(
        session, queue, knowledge_base_id=knowledge_base_id, document_id=document.id
    )
    return DocumentRead.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
def delete_document(
    knowledge_base_id: str,
    document_id: str,
    session: SessionDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
    _editor: EditorDep,
) -> Response:
    """Delete a document, its indexed passages and the content stored for it."""
    DocumentService(session, storage, vector_store).delete(knowledge_base_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _read_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, refusing anything above ``max_bytes``.

    Reading incrementally means an oversized upload is rejected without ever being
    held in memory in full. The limit lives here rather than in the domain because
    it protects the process instead of expressing a business rule.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(
                f"Documents may not exceed {max_bytes} bytes.",
                details={"max_upload_size_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)
