"""The evaluation use case: ingest a labelled corpus, query it, score the result.

An evaluation owns everything it needs. It creates a knowledge base of its own, ingests
the dataset's corpus into it, asks every question through the same query pipeline the API
serves, scores retrieval against the labels, and removes the knowledge base again. The
corpus travels with the dataset, so two runs of the same dataset are comparable and
nothing already in the platform can influence the numbers.

Only metrics that follow from the labels are computed. Nothing here judges the content of
an answer: an answer is scored by whether the chunks it cited are the ones the labels say
are relevant, which is a fact about the citation list rather than an opinion about the
prose.

The run is synchronous and costs the ingestion of the corpus plus the answering of every
question. That is honest for the tens of documents and questions a request can carry;
evaluating a real corpus belongs in a batch job.
"""

from __future__ import annotations

import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import MetricsRegistry
from app.core.statistics import mean, summarise
from app.core.timing import elapsed_ms
from app.evaluation import (
    AnswerAggregate,
    EvaluationDataset,
    EvaluationQuestion,
    EvaluationReport,
    LatencyAggregate,
    QuestionReport,
    RetrievalAggregate,
    citation_precision,
    citation_recall,
    score_retrieval,
)
from app.models import Chunk, DocumentStatus
from app.rag import AnswerModel, EmbeddingModel, Reranker, VectorStore
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.storage import DocumentStorage
from app.schemas.knowledge_base import KnowledgeBaseCreate
from app.services.documents import DocumentService
from app.services.ingestion import IngestionService
from app.services.knowledge_bases import KnowledgeBaseService
from app.services.query import QueryOutcome, QueryService

logger = get_logger(__name__)

ANSWERED = QueryOutcome.ANSWERED.value
INSUFFICIENT_EVIDENCE = QueryOutcome.INSUFFICIENT_EVIDENCE.value


class EvaluationService:
    """Runs one labelled dataset against a temporary knowledge base."""

    def __init__(
        self,
        *,
        session: Session,
        storage: DocumentStorage,
        vector_store: VectorStore,
        embedder: EmbeddingModel,
        reranker: Reranker | None,
        answer_model: AnswerModel,
        ingestion: IngestionService,
        settings: Settings,
        metrics: MetricsRegistry,
    ) -> None:
        self._session = session
        self._storage = storage
        self._vector_store = vector_store
        self._embedder = embedder
        self._reranker = reranker
        self._answer_model = answer_model
        self._ingestion = ingestion
        self._settings = settings
        self._metrics = metrics

    def run(
        self,
        dataset: EvaluationDataset,
        *,
        k: int | None = None,
        min_score: float | None = None,
    ) -> EvaluationReport:
        """Ingest the corpus, answer every question, and score what came back.

        ``k`` and ``min_score`` override the configured retrieval policy for this run and
        are reported back with the results, because a number produced under a different
        threshold than the one the server serves cannot be read without it.
        """
        started = time.perf_counter()
        top_k = self._settings.retrieval_top_k if k is None else k
        threshold = self._settings.retrieval_min_score if min_score is None else min_score
        issues: list[str] = []

        knowledge_base_id = self._create_knowledge_base(dataset)
        try:
            chunks = self._ingest_corpus(dataset, knowledge_base_id, issues)
            reports = [
                self._evaluate_question(
                    question, knowledge_base_id, chunks, top_k, threshold, issues
                )
                for question in dataset.questions
            ]
        finally:
            self._remove_knowledge_base(knowledge_base_id)

        report = self._aggregate(
            dataset=dataset,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
            threshold=threshold,
            chunks=chunks,
            reports=reports,
            issues=issues,
        )
        self._metrics.increment("evaluation.runs")
        self._metrics.increment("evaluation.questions.total", len(dataset.questions))
        self._metrics.observe("evaluation", elapsed_ms(started))
        logger.info(
            "evaluation_completed",
            dataset=dataset.name,
            questions=len(reports),
            scorable=report.retrieval.questions if report.retrieval is not None else 0,
            answered=report.answers.answered,
            insufficient_evidence=report.answers.insufficient_evidence,
            issues=len(issues),
            duration_ms=elapsed_ms(started),
        )
        return report

    def _create_knowledge_base(self, dataset: EvaluationDataset) -> str:
        """Create the knowledge base this run owns.

        The name is generated rather than taken from the dataset, because names are unique
        across the platform and an evaluation must not collide with a real knowledge base
        -- or with a previous run's leftovers.
        """
        knowledge_base = KnowledgeBaseService(
            self._session, self._storage, self._vector_store
        ).create(
            KnowledgeBaseCreate(
                name=f"evaluation-{uuid4().hex[:12]}",
                description=f"Temporary knowledge base for the {dataset.name!r} evaluation.",
            )
        )
        return knowledge_base.id

    def _ingest_corpus(
        self, dataset: EvaluationDataset, knowledge_base_id: str, issues: list[str]
    ) -> dict[str, list[Chunk]]:
        """Upload and ingest the corpus, returning the stored chunks per document.

        Ingestion runs in its own sessions, so the uploads are committed before it starts:
        an uncommitted insert is invisible to another connection and holds a write lock
        that ingestion would then contend with. That is also why the documents are re-read
        afterwards instead of being trusted from memory.
        """
        documents = DocumentService(self._session, self._storage, self._vector_store)
        registered: dict[str, str] = {}
        for document in dataset.documents:
            uploaded = documents.upload(
                knowledge_base_id,
                filename=document.name,
                content_type=None,
                content=document.content.encode("utf-8"),
            )
            registered[document.name] = uploaded.id

        self._session.commit()

        for document_id in registered.values():
            self._ingestion.run(knowledge_base_id, document_id)

        # Ingestion committed through its own sessions while this one holds instances
        # believed to be current, and the factory does not expire on commit. Expiring them
        # forces the reads below to come from the database, where the ingestion wrote.
        self._session.expire_all()
        repository = DocumentRepository(self._session)
        chunks_by_document: dict[str, list[Chunk]] = {}
        for name, document_id in registered.items():
            document = repository.get(knowledge_base_id, document_id)
            if document is None or document.status != DocumentStatus.READY.value:
                status = document.status if document is not None else "missing"
                reason = document.error_message if document is not None else None
                issues.append(
                    f"Document {name!r} did not ingest (status {status}"
                    f"{f': {reason}' if reason else ''})."
                )
                chunks_by_document[name] = []
                continue
            chunks_by_document[name] = ChunkRepository(self._session).list_for_document(document_id)
        return chunks_by_document

    def _evaluate_question(
        self,
        question: EvaluationQuestion,
        knowledge_base_id: str,
        chunks_by_document: dict[str, list[Chunk]],
        top_k: int,
        threshold: float,
        issues: list[str],
    ) -> QuestionReport:
        """Answer one question and score it against the labels that resolved."""
        problems: list[str] = []
        relevant: set[str] = set()

        if question.answerable:
            for label in question.relevant:
                matches = [
                    chunk.id
                    for chunk in chunks_by_document.get(label.document, [])
                    if label.contains in chunk.content
                ]
                if not matches:
                    problems.append(f"no chunk of {label.document!r} contains the labelled snippet")
                    issues.append(
                        f"Question {question.id!r}: no chunk of {label.document!r} contains "
                        f"{label.contains!r}."
                    )
                relevant.update(matches)

        # The question is asked through the same service the API uses, with the same
        # settings, so what is measured is what a caller would get.
        result = QueryService(
            session=self._session,
            embedder=self._embedder,
            vector_store=self._vector_store,
            reranker=self._reranker,
            answer_model=self._answer_model,
            settings=self._settings,
            metrics=self._metrics,
        ).answer(knowledge_base_id, question.question, top_k=top_k, min_score=threshold)

        retrieved = [passage.chunk_id for passage in result.retrieval.passages]
        cited = [citation.chunk_id for citation in result.citations]
        score = score_retrieval(retrieved, relevant, top_k) if relevant else None
        cited_precision = citation_precision(cited, relevant) if relevant and cited else None
        cited_recall = citation_recall(cited, relevant) if relevant else None

        return QuestionReport(
            id=question.id,
            question=question.question,
            answerable=question.answerable,
            outcome=result.outcome.value,
            answer_kind=result.answer_kind,
            citations=len(result.citations),
            relevant_chunks=len(relevant),
            retrieved_chunks=len(retrieved),
            matched_chunks=None if score is None else score.matched,
            recall=None if score is None else score.recall,
            precision=None if score is None else score.precision,
            reciprocal_rank=None if score is None else score.reciprocal_rank,
            ndcg=None if score is None else score.ndcg,
            citation_precision=cited_precision,
            citation_recall=cited_recall,
            retrieval_ms=result.retrieval.duration_ms,
            generation_ms=(None if result.generation is None else result.generation.duration_ms),
            total_ms=result.total_duration_ms,
            issues=tuple(problems),
        )

    def _aggregate(
        self,
        *,
        dataset: EvaluationDataset,
        knowledge_base_id: str,
        top_k: int,
        threshold: float,
        chunks: dict[str, list[Chunk]],
        reports: list[QuestionReport],
        issues: list[str],
    ) -> EvaluationReport:
        """Average the per-question results, skipping the ones that cannot be averaged."""
        scorable = [report for report in reports if report.recall is not None]
        retrieval = (
            RetrievalAggregate(
                questions=len(scorable),
                k=top_k,
                recall=mean([report.recall for report in scorable if report.recall is not None]),
                precision=mean(
                    [report.precision for report in scorable if report.precision is not None]
                ),
                # A hit is exactly "at least one relevant chunk was retrieved", which the
                # match count already states; no separate per-question field is carried.
                hit_rate=mean(
                    [1.0 if (report.matched_chunks or 0) > 0 else 0.0 for report in scorable]
                ),
                mrr=mean(
                    [
                        report.reciprocal_rank
                        for report in scorable
                        if report.reciprocal_rank is not None
                    ]
                ),
                ndcg=mean([report.ndcg for report in scorable if report.ndcg is not None]),
            )
            if scorable
            else None
        )

        answerable = [report for report in reports if report.answerable]
        unanswerable = [report for report in reports if not report.answerable]
        answered = [report for report in reports if report.outcome == ANSWERED]
        cited = [report for report in reports if report.citation_precision is not None]

        answers = AnswerAggregate(
            answered=len(answered),
            insufficient_evidence=len(reports) - len(answered),
            answerable_answered=(
                len([report for report in answerable if report.outcome == ANSWERED])
                / len(answerable)
                if answerable
                else None
            ),
            unanswerable_abstained=(
                len([report for report in unanswerable if report.outcome == INSUFFICIENT_EVIDENCE])
                / len(unanswerable)
                if unanswerable
                else None
            ),
            citation_precision=(
                mean(
                    [
                        report.citation_precision
                        for report in cited
                        if report.citation_precision is not None
                    ]
                )
                if cited
                else None
            ),
            citation_recall=(
                mean(
                    [
                        report.citation_recall
                        for report in cited
                        if report.citation_recall is not None
                    ]
                )
                if cited
                else None
            ),
        )

        generation_ms = [
            report.generation_ms for report in reports if report.generation_ms is not None
        ]
        latency = LatencyAggregate(
            retrieval=summarise([report.retrieval_ms for report in reports]),
            generation=summarise(generation_ms) if generation_ms else None,
            total=summarise([report.total_ms for report in reports]),
        )

        return EvaluationReport(
            dataset=dataset.name,
            temporary_knowledge_base_id=knowledge_base_id,
            k=top_k,
            min_score=threshold,
            documents=len(dataset.documents),
            chunks=sum(len(chunks_of) for chunks_of in chunks.values()),
            total_questions=len(reports),
            answerable=len(answerable),
            unanswerable=len(unanswerable),
            retrieval=retrieval,
            answers=answers,
            latency=latency,
            issues=tuple(issues),
            per_question=tuple(reports),
        )

    def _remove_knowledge_base(self, knowledge_base_id: str) -> None:
        """Remove the temporary knowledge base, whatever happened during the run.

        A leftover evaluation corpus would be searchable through the API and would make
        the next run's numbers depend on what the last one left behind. The rollback comes
        first so that a failed run cannot leave a broken transaction behind that would
        make the cleanup itself fail.
        """
        try:
            self._session.rollback()
            KnowledgeBaseService(self._session, self._storage, self._vector_store).delete(
                knowledge_base_id
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception("evaluation_cleanup_failed", knowledge_base_id=knowledge_base_id)
