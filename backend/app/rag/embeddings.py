"""Port for turning text into embedding vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.errors import AppError


@runtime_checkable
class EmbeddingModel(Protocol):
    """Produces embedding vectors for documents and for queries.

    Document and query embedding are separate entry points because providers often
    treat them differently: some prefix queries with an instruction, others use an
    asymmetric encoder pair. Keeping them separate means the adapter, not the
    pipeline, decides.
    """

    @property
    def dimensions(self) -> int:
        """Length of every vector this model produces."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of chunk texts, one vector per text, in order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        ...


class EmbeddingFailedError(AppError):
    """An embedding provider could not turn text into a vector.

    It is declared beside the port rather than in :mod:`app.core.errors` for the same
    reason ``DocumentStorageError`` is declared beside the storage port: the port
    defines what can go wrong in its own terms, and every implementation raises this.
    It is an ``AppError`` so that a provider failure is reported as a bad gateway
    rather than as an internal fault of this service.
    """

    status_code = 502
    code = "EMBEDDING_FAILED"
    message = "The text could not be embedded."
