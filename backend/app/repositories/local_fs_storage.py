"""Filesystem implementation of the document storage port."""

from __future__ import annotations

from pathlib import Path

from app.repositories.storage import DocumentStorageError


class LocalFileSystemStorage:
    """Stores document content as files beneath a root directory.

    Directory creation is deferred to the first write, so constructing the adapter
    (which happens while the application is being assembled) never touches disk.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        """The directory that stored objects are rooted in."""
        return self._root

    def save(self, key: str, content: bytes) -> None:
        path = self._resolve(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError as exc:  # pragma: no cover - depends on the host filesystem
            raise DocumentStorageError(f"could not write object {key!r}") from exc

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - depends on the host filesystem
            raise DocumentStorageError(f"could not delete object {key!r}") from exc

    def _resolve(self, key: str) -> Path:
        """Map a storage key to a path, refusing anything outside the root.

        Storage keys are derived from caller-supplied identifiers, so traversal
        attempts are rejected rather than sanitised silently.
        """
        root = self._root.resolve()
        candidate = (root / key).resolve()
        if candidate != root and root not in candidate.parents:
            raise DocumentStorageError(f"storage key {key!r} escapes the storage root")
        return candidate
