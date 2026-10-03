"""Port for turning text into embedding vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


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
