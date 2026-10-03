"""Port for vector similarity search."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.errors import AppError


@dataclass(frozen=True)
class VectorRecord:
    """One indexed chunk.

    The index stores identifiers and vectors only. Chunk text lives in the database,
    so a search result is resolved back to its passage instead of the index keeping a
    second, drifting copy of the corpus.
    """

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class VectorMatch:
    """A scored search result."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    score: float


@runtime_checkable
class VectorStore(Protocol):
    """Indexes chunk vectors and answers nearest-neighbour queries."""

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        """Insert or replace records, keyed by chunk id."""
        ...

    def delete_document(self, document_id: str) -> None:
        """Remove every vector belonging to a document."""
        ...

    def search(
        self, vector: Sequence[float], *, knowledge_base_id: str, top_k: int = 5
    ) -> list[VectorMatch]:
        """Return the best matches inside one knowledge base, best first."""
        ...

    def count(self) -> int:
        """Return how many vectors are indexed."""
        ...


class VectorStoreError(AppError):
    """The vector index could not be read or written.

    Declared beside the port for the same reason as :class:`EmbeddingFailedError`. A
    store that cannot be reached is an upstream failure of answering a question, so it
    maps onto the API contract as a bad gateway rather than as a crash of this service.
    """

    status_code = 502
    code = "VECTOR_STORE_ERROR"
    message = "The vector index could not be reached."
