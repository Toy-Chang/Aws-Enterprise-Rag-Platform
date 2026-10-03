"""In-process vector index."""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence

from app.rag.vector_store import VectorMatch, VectorRecord


class InMemoryVectorStore:
    """A brute-force cosine index held in process memory.

    Scoring every indexed vector is deliberate: it keeps the local adapter free of
    dependencies and free of approximation, so tests assert exact ordering. The real
    index is OpenSearch or pgvector in the AWS deployment, behind the same port.

    Two properties are worth stating plainly. Search returns the best candidates
    regardless of how low their score is, because deciding that nothing is relevant
    enough is a retrieval policy, not an index concern. And a lock guards the index
    because ingestion runs on a worker thread while requests search concurrently.
    """

    def __init__(self, dimensions: int) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions
        self._records: dict[str, VectorRecord] = {}
        self._lock = threading.RLock()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        for record in records:
            if len(record.vector) != self._dimensions:
                raise ValueError(
                    f"chunk {record.chunk_id!r} has {len(record.vector)} dimensions, "
                    f"but the index is configured for {self._dimensions}"
                )
        with self._lock:
            for record in records:
                self._records[record.chunk_id] = record

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            stale = [
                chunk_id
                for chunk_id, record in self._records.items()
                if record.document_id == document_id
            ]
            for chunk_id in stale:
                del self._records[chunk_id]

    def search(
        self, vector: Sequence[float], *, knowledge_base_id: str, top_k: int = 5
    ) -> list[VectorMatch]:
        if len(vector) != self._dimensions:
            raise ValueError(
                f"query has {len(vector)} dimensions, "
                f"but the index is configured for {self._dimensions}"
            )
        if top_k < 1:
            return []

        with self._lock:
            scored = [
                (record, _cosine_similarity(vector, record.vector))
                for record in self._records.values()
                if record.knowledge_base_id == knowledge_base_id
            ]

        # Chunk id breaks score ties so that equal-scoring passages come back in a
        # stable order rather than in dictionary order.
        scored.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return [
            VectorMatch(
                chunk_id=record.chunk_id,
                document_id=record.document_id,
                knowledge_base_id=record.knowledge_base_id,
                score=score,
            )
            for record, score in scored[:top_k]
        ]

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        """Drop every indexed vector."""
        with self._lock:
            self._records.clear()


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors of equal length."""
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b

    if left_norm == 0.0 or right_norm == 0.0:
        # A zero vector has no direction, so it is similar to nothing.
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))
