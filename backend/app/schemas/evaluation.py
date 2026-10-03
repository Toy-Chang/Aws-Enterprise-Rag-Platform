"""Request and response schemas for the evaluation endpoint.

The caps on the payload are the bounds of a synchronous run: an evaluation ingests its
whole corpus and answers every question before it returns, so the request that carries the
corpus is also the request that does the work. Evaluating a corpus larger than this belongs
in a batch job rather than in a request.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.statistics import Summary
from app.evaluation import (
    CorpusDocument,
    EvaluationDataset,
    EvaluationQuestion,
    EvaluationReport,
    RelevanceLabel,
)

MAX_DOCUMENTS = 25
MAX_QUESTIONS = 100
MAX_DOCUMENT_CHARS = 100_000
MAX_LABELS_PER_QUESTION = 20


class EvaluationDocument(BaseModel):
    """One document of the corpus the evaluation ingests."""

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Filename including its extension: the parser is chosen from it.",
    )
    content: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)


class EvaluationLabel(BaseModel):
    """A passage of the corpus that answers a question."""

    document: str = Field(min_length=1, max_length=255, description="A document of the corpus.")
    contains: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "A snippet that identifies the relevant passage. Every chunk whose text "
            "contains it counts as relevant, so it may resolve to more than one chunk."
        ),
    )


class EvaluationQuestionPayload(BaseModel):
    """A question, and what answers it if anything does."""

    id: str = Field(
        min_length=1, max_length=100, description="Identifies the question in the report."
    )
    question: str = Field(min_length=1, max_length=2000)
    answerable: bool = Field(
        default=True,
        description=(
            "Whether the corpus answers this question. An answerable question must label "
            "at least one relevant passage; an unanswerable one must label none, and what "
            "it measures is whether the platform abstains."
        ),
    )
    relevant: list[EvaluationLabel] = Field(
        default_factory=list, max_length=MAX_LABELS_PER_QUESTION
    )


class EvaluationRequest(BaseModel):
    """A labelled dataset to run."""

    name: str = Field(default="evaluation", min_length=1, max_length=120)
    k: int = Field(default=5, ge=1, le=50, description="Results considered per question.")
    min_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description=(
            "Similarity below which a passage is not treated as evidence. Defaults to the "
            "server's configured threshold; setting it is how a different threshold policy "
            "is measured rather than guessed at."
        ),
    )
    documents: list[EvaluationDocument] = Field(min_length=1, max_length=MAX_DOCUMENTS)
    questions: list[EvaluationQuestionPayload] = Field(min_length=1, max_length=MAX_QUESTIONS)

    def to_dataset(self) -> EvaluationDataset:
        """Convert the payload into the dataset the harness runs.

        Raises :class:`InvalidEvaluationDatasetError` for anything the schema cannot
        express, such as a label naming a document the corpus does not contain.
        """
        return EvaluationDataset.create(
            name=self.name,
            documents=[
                CorpusDocument(name=document.name, content=document.content)
                for document in self.documents
            ],
            questions=[
                EvaluationQuestion(
                    id=question.id,
                    question=question.question,
                    answerable=question.answerable,
                    relevant=tuple(
                        RelevanceLabel(document=label.document, contains=label.contains)
                        for label in question.relevant
                    ),
                )
                for question in self.questions
            ],
        )


class SummaryRead(BaseModel):
    """A distribution of measurements, in milliseconds."""

    count: int
    mean: float
    minimum: float
    p50: float
    p95: float = Field(description="Nearest-rank 95th percentile: a value that was measured.")
    maximum: float

    @classmethod
    def from_summary(cls, summary: Summary) -> SummaryRead:
        return cls(
            count=summary.count,
            mean=summary.mean,
            minimum=summary.minimum,
            p50=summary.p50,
            p95=summary.p95,
            maximum=summary.maximum,
        )


class RetrievalMetricsRead(BaseModel):
    """Mean retrieval metrics over the questions that could be scored."""

    questions: int = Field(description="How many questions these means were computed from.")
    k: int
    recall_at_k: float = Field(description="Share of the labelled-relevant chunks retrieved.")
    precision_at_k: float = Field(
        description="Share of the first k slots holding a relevant chunk."
    )
    hit_rate_at_k: float = Field(description="Share of questions with at least one relevant chunk.")
    mrr: float = Field(description="Mean reciprocal rank of the first relevant chunk.")
    ndcg_at_k: float = Field(description="Mean normalised discounted cumulative gain.")


class AnswerMetricsRead(BaseModel):
    """How often the platform answered, and whether its citations were on target.

    A rate is ``null`` when its denominator is zero: a dataset with no unanswerable
    question has not shown that the platform abstains, and reporting 1.0 would claim it
    from no observations.
    """

    answered: int
    insufficient_evidence: int
    answerable_answered: float | None
    unanswerable_abstained: float | None
    citation_precision: float | None = Field(
        description="Share of cited chunks that the labels mark relevant."
    )
    citation_recall: float | None = Field(
        description="Share of labelled-relevant chunks that were cited."
    )


class EvaluationLatencyRead(BaseModel):
    """Latency over every question that ran, whether or not it could be scored."""

    retrieval_ms: SummaryRead
    generation_ms: SummaryRead | None = Field(
        description="Null when no question reached the generator."
    )
    total_ms: SummaryRead


class QuestionResultRead(BaseModel):
    """One question, what the pipeline did with it, and how it scored.

    Every metric is ``null`` when the question could not be scored, rather than zero.
    """

    id: str
    question: str
    answerable: bool
    outcome: str
    answer_kind: str | None
    citations: int
    relevant_chunks: int
    retrieved_chunks: int
    matched_chunks: int | None
    recall_at_k: float | None
    precision_at_k: float | None
    reciprocal_rank: float | None
    ndcg_at_k: float | None
    citation_precision: float | None
    citation_recall: float | None
    retrieval_ms: float
    generation_ms: float | None
    total_ms: float
    issues: list[str] = Field(description="Dataset problems that affected this question.")


class EvaluationResponse(BaseModel):
    """The result of one evaluation run.

    The report is self-contained: the temporary knowledge base is removed before this is
    returned, so the corpus does not stay behind in the platform.
    """

    dataset: str
    temporary_knowledge_base_id: str = Field(
        description="Removed before the response was returned; kept for log correlation."
    )
    k: int
    min_score: float = Field(description="Similarity threshold these results were produced under.")
    documents: int
    chunks: int
    total_questions: int
    answerable: int
    unanswerable: int
    retrieval: RetrievalMetricsRead | None = Field(
        description="Null when no question had a resolvable label."
    )
    answers: AnswerMetricsRead
    latency: EvaluationLatencyRead
    issues: list[str] = Field(
        description="Dataset problems, such as a label snippet that matched no chunk."
    )
    per_question: list[QuestionResultRead]

    @classmethod
    def from_report(cls, report: EvaluationReport) -> EvaluationResponse:
        return cls(
            dataset=report.dataset,
            temporary_knowledge_base_id=report.temporary_knowledge_base_id,
            k=report.k,
            min_score=report.min_score,
            documents=report.documents,
            chunks=report.chunks,
            total_questions=report.total_questions,
            answerable=report.answerable,
            unanswerable=report.unanswerable,
            retrieval=(
                None
                if report.retrieval is None
                else RetrievalMetricsRead(
                    questions=report.retrieval.questions,
                    k=report.retrieval.k,
                    recall_at_k=report.retrieval.recall,
                    precision_at_k=report.retrieval.precision,
                    hit_rate_at_k=report.retrieval.hit_rate,
                    mrr=report.retrieval.mrr,
                    ndcg_at_k=report.retrieval.ndcg,
                )
            ),
            answers=AnswerMetricsRead(
                answered=report.answers.answered,
                insufficient_evidence=report.answers.insufficient_evidence,
                answerable_answered=report.answers.answerable_answered,
                unanswerable_abstained=report.answers.unanswerable_abstained,
                citation_precision=report.answers.citation_precision,
                citation_recall=report.answers.citation_recall,
            ),
            latency=EvaluationLatencyRead(
                retrieval_ms=SummaryRead.from_summary(report.latency.retrieval),
                generation_ms=(
                    None
                    if report.latency.generation is None
                    else SummaryRead.from_summary(report.latency.generation)
                ),
                total_ms=SummaryRead.from_summary(report.latency.total),
            ),
            issues=list(report.issues),
            per_question=[
                QuestionResultRead(
                    id=question.id,
                    question=question.question,
                    answerable=question.answerable,
                    outcome=question.outcome,
                    answer_kind=question.answer_kind,
                    citations=question.citations,
                    relevant_chunks=question.relevant_chunks,
                    retrieved_chunks=question.retrieved_chunks,
                    matched_chunks=question.matched_chunks,
                    recall_at_k=question.recall,
                    precision_at_k=question.precision,
                    reciprocal_rank=question.reciprocal_rank,
                    ndcg_at_k=question.ndcg,
                    citation_precision=question.citation_precision,
                    citation_recall=question.citation_recall,
                    retrieval_ms=question.retrieval_ms,
                    generation_ms=question.generation_ms,
                    total_ms=question.total_ms,
                    issues=list(question.issues),
                )
                for question in report.per_question
            ],
        )
