"""A retrieved passage, carrying everything a citation needs."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Passage:
    """One chunk returned by retrieval, resolved against the database.

    The text comes from the stored chunk rather than from the index, so a passage is
    always exactly what was ingested. ``score`` is the similarity the index reported;
    ``rerank_score`` is the second-stage score, and is ``None`` when no reranker ran.
    """

    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    content: str
    page_number: int | None
    heading_path: tuple[str, ...]
    score: float
    rerank_score: float | None = None

    @property
    def label(self) -> str:
        """Where the passage came from, as a reader would describe it."""
        location = " › ".join(self.heading_path)
        if self.page_number is not None:
            page = f"page {self.page_number}"
            location = f"{location} ({page})" if location else page

        if location:
            return f"{self.document_name} — {location}"
        return self.document_name

    def scored_by_reranker(self, rerank_score: float) -> Passage:
        """Return this passage with a second-stage score attached."""
        return replace(self, rerank_score=rerank_score)
