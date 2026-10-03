"""Query use case: a question in, a grounded answer with citations out."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import MetricsRegistry
from app.core.timing import elapsed_ms
from app.rag import (
    AnswerModel,
    AnswerRequest,
    EmbeddingModel,
    Passage,
    Reranker,
    VectorStore,
    build_context,
)
from app.services.retrieval import RetrievalResult, RetrievalService

logger = get_logger(__name__)

#: Citations quote a bounded amount of text; the full passage is a request away.
SNIPPET_CHARS = 280


class QueryOutcome(enum.StrEnum):
    """How a query ended."""

    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class Citation:
    """A passage the answer was built from, with the score that selected it."""

    marker: int
    document_id: str
    document_name: str
    chunk_id: str
    chunk_index: int
    page_number: int | None
    heading_path: tuple[str, ...]
    score: float
    rerank_score: float | None
    snippet: str


@dataclass(frozen=True, slots=True)
class Usage:
    """Token usage, when the generator reports it."""

    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class ContextInfo:
    """How much of the retrieval actually reached the generator."""

    chars: int
    passages: int
    skipped: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Which generator ran, and how long it took."""

    model: str
    kind: str
    duration_ms: float


@dataclass(frozen=True, slots=True)
class QueryResult:
    """A complete answer, its evidence, and the stages that produced it."""

    question: str
    knowledge_base_id: str
    outcome: QueryOutcome
    answer: str | None
    answer_kind: str | None
    citations: tuple[Citation, ...]
    usage: Usage
    retrieval: RetrievalResult
    context: ContextInfo
    generation: GenerationResult | None
    total_duration_ms: float


class QueryService:
    """Answers questions from one knowledge base.

    The service never answers from a model's own knowledge: retrieval decides whether
    there is evidence, and only then is a generator asked to phrase it. That ordering is
    what makes ``insufficient_evidence`` a real outcome rather than a prompt
    instruction the model may ignore.
    """

    def __init__(
        self,
        *,
        session: Session,
        embedder: EmbeddingModel,
        vector_store: VectorStore,
        reranker: Reranker | None,
        answer_model: AnswerModel,
        settings: Settings,
        metrics: MetricsRegistry,
    ) -> None:
        self._retrieval = RetrievalService(
            session=session,
            embedder=embedder,
            vector_store=vector_store,
            reranker=reranker,
            settings=settings,
        )
        self._answer_model = answer_model
        self._metrics = metrics
        self._context_max_chars = settings.context_max_chars

    def answer(
        self,
        knowledge_base_id: str,
        question: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> QueryResult:
        """Retrieve evidence for ``question`` and answer from it."""
        started = time.perf_counter()
        retrieval = self._retrieval.retrieve(
            knowledge_base_id, question, top_k=top_k, min_score=min_score
        )
        bundle = build_context(retrieval.passages, max_chars=self._context_max_chars)
        context = ContextInfo(
            chars=len(bundle.text),
            passages=len(bundle.passages),
            skipped=bundle.skipped,
            truncated=bundle.truncated,
        )

        if not bundle.passages:
            # Nothing cleared the threshold, or the knowledge base holds nothing that is
            # ready. Reporting that is the point of the threshold: an unsupported answer
            # is worse than no answer.
            logger.info(
                "query_insufficient_evidence",
                knowledge_base_id=knowledge_base_id,
                candidates=retrieval.candidates,
                above_threshold=retrieval.above_threshold,
                min_score=retrieval.min_score,
            )
            return self._finish(
                QueryResult(
                    question=question,
                    knowledge_base_id=knowledge_base_id,
                    outcome=QueryOutcome.INSUFFICIENT_EVIDENCE,
                    answer=None,
                    answer_kind=None,
                    citations=(),
                    usage=Usage(input_tokens=None, output_tokens=None),
                    retrieval=retrieval,
                    context=context,
                    generation=None,
                    total_duration_ms=elapsed_ms(started),
                )
            )

        generation_started = time.perf_counter()
        generated = self._answer_model.answer(
            AnswerRequest(question=question, context=bundle.text, passages=bundle.passages)
        )
        generation = GenerationResult(
            model=self._answer_model.name,
            kind=self._answer_model.kind,
            duration_ms=elapsed_ms(generation_started),
        )

        result = QueryResult(
            question=question,
            knowledge_base_id=knowledge_base_id,
            outcome=QueryOutcome.ANSWERED,
            answer=generated.text,
            answer_kind=self._answer_model.kind,
            citations=tuple(
                _citation(marker, passage)
                for marker, passage in enumerate(bundle.passages, start=1)
            ),
            usage=Usage(input_tokens=generated.input_tokens, output_tokens=generated.output_tokens),
            retrieval=retrieval,
            context=context,
            generation=generation,
            total_duration_ms=elapsed_ms(started),
        )
        logger.info(
            "query_answered",
            knowledge_base_id=knowledge_base_id,
            citations=len(result.citations),
            generator=generation.model,
            generator_kind=generation.kind,
            retrieval_ms=retrieval.duration_ms,
            generation_ms=generation.duration_ms,
            total_ms=result.total_duration_ms,
        )
        return self._finish(result)

    def _finish(self, result: QueryResult) -> QueryResult:
        """Record the stages of one query and return it.

        The stage durations are the ones already measured for the trace, so the
        metrics and the response cannot report different numbers for the same call.
        Token counts are recorded only when the generator reports them: counting a
        missing usage report as zero would understate what the model actually did.
        """
        self._metrics.observe("retrieval", result.retrieval.duration_ms)
        self._metrics.observe("query", result.total_duration_ms)
        self._metrics.increment("retrieval.candidates.total", result.retrieval.candidates)
        self._metrics.increment("retrieval.selected.total", len(result.retrieval.passages))

        if result.outcome is QueryOutcome.ANSWERED:
            self._metrics.increment("query.answered")
        else:
            self._metrics.increment("query.insufficient_evidence")

        if result.generation is not None:
            self._metrics.observe("generation", result.generation.duration_ms)
        if result.usage.input_tokens is not None:
            self._metrics.increment("generation.input_tokens.total", result.usage.input_tokens)
        if result.usage.output_tokens is not None:
            self._metrics.increment("generation.output_tokens.total", result.usage.output_tokens)

        return result


def _citation(marker: int, passage: Passage) -> Citation:
    return Citation(
        marker=marker,
        document_id=passage.document_id,
        document_name=passage.document_name,
        chunk_id=passage.chunk_id,
        chunk_index=passage.chunk_index,
        page_number=passage.page_number,
        heading_path=passage.heading_path,
        score=round(passage.score, 6),
        rerank_score=(round(passage.rerank_score, 6) if passage.rerank_score is not None else None),
        snippet=_snippet(passage.content),
    )


def _snippet(content: str) -> str:
    """Collapse whitespace and cut to a length a client can display."""
    text = " ".join(content.split())
    if len(text) <= SNIPPET_CHARS:
        return text

    cut = text[:SNIPPET_CHARS]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut}…"
