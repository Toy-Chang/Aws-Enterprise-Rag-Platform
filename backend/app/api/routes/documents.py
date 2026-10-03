"""Document endpoints, nested under a knowledge base."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status

from app.api.deps import SessionDep, SettingsDep, StorageDep
from app.core.errors import PayloadTooLargeError
from app.schemas.document import DocumentRead
from app.services.documents import DocumentService

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}/documents", tags=["documents"])

_READ_CHUNK_BYTES = 1024 * 1024


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
    settings: SettingsDep,
) -> DocumentRead:
    """Store a document in a knowledge base.

    The document is registered immediately with status ``pending``. Parsing,
    chunking and indexing belong to the ingestion phase, which moves the status on
    from there.
    """
    content = _read_within_limit(file, settings.max_upload_size_bytes)
    document = DocumentService(session, storage).upload(
        knowledge_base_id,
        filename=file.filename,
        content_type=file.content_type,
        content=content,
    )
    return DocumentRead.model_validate(document)


@router.get("", summary="List the documents of a knowledge base")
def list_documents(
    knowledge_base_id: str, session: SessionDep, storage: StorageDep
) -> list[DocumentRead]:
    """Return the documents of a knowledge base, newest first."""
    documents = DocumentService(session, storage).list_for_knowledge_base(knowledge_base_id)
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", summary="Get document metadata")
def get_document(
    knowledge_base_id: str, document_id: str, session: SessionDep, storage: StorageDep
) -> DocumentRead:
    """Return the metadata of one document."""
    document = DocumentService(session, storage).get(knowledge_base_id, document_id)
    return DocumentRead.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
def delete_document(
    knowledge_base_id: str, document_id: str, session: SessionDep, storage: StorageDep
) -> Response:
    """Delete a document and the content stored for it."""
    DocumentService(session, storage).delete(knowledge_base_id, document_id)
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
