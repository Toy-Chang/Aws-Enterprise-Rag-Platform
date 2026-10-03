"""What an evaluation run produced."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.statistics import Summary


@dataclass(frozen=True, slots=True)
class QuestionReport:
    """One question, what the pipeline did with it, and how it scored.

    A metric is ``None`` when the question could not be scored: an unanswerable question
    has no retrieval metrics, an unanswered one has no citations to judge, and a label
    that resolved to no chunk leaves nothing to compare against. Reporting zero in those
    cases would invent a measurement.
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
    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    ndcg: float | None
    citation_precision: float | None
    citation_recall: float | None
    retrieval_ms: float
    generation_ms: float | None
    total_ms: float
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalAggregate:
    """Mean retrieval metrics over the questions that could be scored."""

    questions: int
    k: int
    recall: float
    precision: float
    hit_rate: float
    mrr: float
    ndcg: float


@dataclass(frozen=True, slots=True)
class AnswerAggregate:
    """How often the platform answered, and whether its citations were on target.

    A rate whose denominator is zero is ``None`` rather than 1.0: a dataset with no
    unanswerable question has not demonstrated that the platform abstains, and claiming a
    perfect rate from no observations would be the clearest kind of exaggeration.
    """

    answered: int
    insufficient_evidence: int
    answerable_answered: float | None
    unanswerable_abstained: float | None
    citation_precision: float | None
    citation_recall: float | None


@dataclass(frozen=True, slots=True)
class LatencyAggregate:
    """Latency over every question that ran, whether or not it could be scored."""

    retrieval: Summary
    generation: Summary | None
    total: Summary


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """A complete account of one evaluation run.

    The report stands alone: the corpus it used is removed before the run returns, so
    everything needed to read the numbers -- the dataset name, its size, the metrics, the
    per-question detail and any dataset problems -- is in here.
    """

    dataset: str
    temporary_knowledge_base_id: str
    k: int
    min_score: float
    documents: int
    chunks: int
    total_questions: int
    answerable: int
    unanswerable: int
    retrieval: RetrievalAggregate | None
    answers: AnswerAggregate
    latency: LatencyAggregate
    issues: tuple[str, ...]
    per_question: tuple[QuestionReport, ...]
