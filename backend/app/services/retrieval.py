"""Retrieval use case: a question in, ranked passages out."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.timing import elapsed_ms
from app.rag import EmbeddingModel, Passage, Reranker, VectorMatch, VectorStore
from app.repositories.chunks import ChunkRepository
from app.repositories.knowledge_bases import KnowledgeBaseRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """What retrieval did, and what it found.

    The counts are kept alongside the passages because they are the difference between
    "the knowledge base has nothing on this" and "the threshold rejected everything",
    which are very different problems to debug.
    """

    passages: tuple[Passage, ...]
    candidates: int
    above_threshold: int
    missing_chunks: int
    reranked: bool
    reranker: str | None
    top_k: int
    min_score: float
    duration_ms: float


class RetrievalService:
    """Finds the passages that could answer a question.

    Retrieval deliberately returns the best candidates regardless of how good they
    are; deciding that nothing is relevant enough is a policy, and it is applied here
    through ``min_score`` so that the index stays a general-purpose component.
    """

    def __init__(
        self,
        *,
        session: Session,
        embedder: EmbeddingModel,
        vector_store: VectorStore,
        reranker: Reranker | None,
        settings: Settings,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._vector_store = vector_store
        self._reranker = reranker
        self._default_top_k = settings.retrieval_top_k
        self._default_min_score = settings.retrieval_min_score
        self._candidate_multiplier = settings.retrieval_candidate_multiplier

    def retrieve(
        self,
        knowledge_base_id: str,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Return the passages that best answer ``question``."""
        started = time.perf_counter()
        limit = self._default_top_k if top_k is None else top_k
        threshold = self._default_min_score if min_score is None else min_score

        if KnowledgeBaseRepository(self._session).get(knowledge_base_id) is None:
            raise NotFoundError(
                f"Knowledge base {knowledge_base_id!r} does not exist.",
                details={"knowledge_base_id": knowledge_base_id},
            )

        # With a reranker in play, more candidates are fetched than will be returned, so
        # that reranking has something to choose between rather than only reordering an
        # already-final list.
        pool = limit * self._candidate_multiplier if self._reranker is not None else limit
        matches = self._vector_store.search(
            self._embedder.embed_query(question),
            knowledge_base_id=knowledge_base_id,
            top_k=pool,
        )
        above_threshold = [match for match in matches if match.score >= threshold]

        passages = self._resolve(above_threshold)
        missing = len(above_threshold) - len(passages)

        reranked = self._reranker is not None
        if self._reranker is not None:
            passages = self._reranker.rerank(question, passages)

        result = RetrievalResult(
            passages=tuple(passages[:limit]),
            candidates=len(matches),
            above_threshold=len(above_threshold),
            missing_chunks=missing,
            reranked=reranked,
            reranker=self._reranker.name if self._reranker is not None else None,
            top_k=limit,
            min_score=threshold,
            duration_ms=elapsed_ms(started),
        )
        logger.info(
            "retrieval_completed",
            knowledge_base_id=knowledge_base_id,
            candidates=result.candidates,
            above_threshold=result.above_threshold,
            used=len(result.passages),
            reranked=result.reranked,
            duration_ms=result.duration_ms,
        )
        return result

    def _resolve(self, matches: Sequence[VectorMatch]) -> list[Passage]:
        """Turn index matches into passages, preserving the ranking."""
        rows = ChunkRepository(self._session).list_with_document_names(
            [match.chunk_id for match in matches]
        )
        by_id = {chunk.id: (chunk, name) for chunk, name in rows}

        passages: list[Passage] = []
        for match in matches:
            row = by_id.get(match.chunk_id)
            if row is None:
                # The index is derived state, so a miss means a deletion raced this
                # search. Skipping it is right; the count is reported so that a pattern
                # of misses is visible rather than silent.
                logger.warning("retrieval_chunk_missing", chunk_id=match.chunk_id)
                continue
            chunk, document_name = row
            passages.append(
                Passage(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=document_name,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading_path=tuple(chunk.heading_path or ()),
                    score=match.score,
                )
            )
        return passages
