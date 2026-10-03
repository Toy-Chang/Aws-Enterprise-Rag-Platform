"""Port for second-stage reranking, and the local adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.rag.passages import Passage
from app.rag.text import terms


@runtime_checkable
class Reranker(Protocol):
    """Re-scores candidates that retrieval already considered relevant."""

    name: str

    def rerank(self, question: str, passages: Sequence[Passage]) -> list[Passage]:
        """Return the passages best first, each carrying its rerank score."""
        ...


class LexicalOverlapReranker:
    """Re-orders passages by how much of the question they actually cover.

    A passage's score is the fraction of the question's distinct terms that appear in
    it, so a passage containing every term outranks one that matched a single repeated
    term in the embedding. Ties fall back to the retrieval score and then to the chunk
    identifier, which keeps the ordering reproducible.

    This is not a learned reranker: it re-weights the same lexical signal the local
    embedding already uses, one level less coarsely, and it exists so the reranking
    stage is a real, testable implementation rather than a placeholder. Nothing here
    claims to improve answer quality, which is why it is disabled by default until
    Phase 5 can measure it against the unranked baseline.
    """

    name = "lexical-overlap"

    def rerank(self, question: str, passages: Sequence[Passage]) -> list[Passage]:
        wanted = set(terms(question))
        if not wanted:
            return list(passages)

        scored = [
            passage.scored_by_reranker(len(wanted & set(terms(passage.content))) / len(wanted))
            for passage in passages
        ]
        return sorted(
            scored,
            key=lambda passage: (
                -(passage.rerank_score or 0.0),
                -passage.score,
                passage.chunk_id,
            ),
        )
