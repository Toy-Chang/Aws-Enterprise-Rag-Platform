"""Port for document content storage.

The port is owned by the domain. Local development uses the filesystem adapter in
this package; the Amazon S3 adapter added alongside the other AWS integrations
implements the same interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class DocumentStorageError(Exception):
    """Raised when a storage backend cannot complete an operation."""


@runtime_checkable
class DocumentStorage(Protocol):
    """Stores and removes document content under an opaque key."""

    def save(self, key: str, content: bytes) -> None:
        """Persist ``content`` under ``key``, replacing any existing object.

        Raises:
            DocumentStorageError: if the backend cannot write the object.
        """
        ...

    def delete(self, key: str) -> None:
        """Remove the object stored under ``key``.

        Deleting a key that does not exist is not an error.

        Raises:
            DocumentStorageError: if the backend cannot remove the object.
        """
        ...
