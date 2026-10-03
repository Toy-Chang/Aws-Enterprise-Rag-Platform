"""Port for document content storage.

The port is owned by the domain. Local development uses the filesystem adapter in
this package; the Amazon S3 adapter added alongside the other AWS integrations
implements the same interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.errors import AppError


class DocumentStorageError(AppError):
    """Raised when a storage backend cannot complete an operation.

    Declared beside the port it belongs to, like the embedding and vector store errors,
    and it carries a status: a backend that cannot be reached or refuses a call is a bad
    gateway rather than a defect in this service.
    """

    status_code = 502
    code = "STORAGE_ERROR"
    message = "The document could not be stored or read."


@runtime_checkable
class DocumentStorage(Protocol):
    """Stores and removes document content under an opaque key."""

    def save(self, key: str, content: bytes) -> None:
        """Persist ``content`` under ``key``, replacing any existing object.

        Raises:
            DocumentStorageError: if the backend cannot write the object.
        """
        ...

    def read(self, key: str) -> bytes:
        """Return the content stored under ``key``.

        Raises:
            DocumentStorageError: if the object is missing or cannot be read.
        """
        ...

    def delete(self, key: str) -> None:
        """Remove the object stored under ``key``.

        Deleting a key that does not exist is not an error.

        Raises:
            DocumentStorageError: if the backend cannot remove the object.
        """
        ...
