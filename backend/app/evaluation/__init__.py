"""Evaluation: measuring retrieval and answers against labelled questions.

The metrics are standard information-retrieval measures computed from explicit relevance
judgements. Nothing here judges an answer's content, and no quality metric is reported
anywhere without the labels to support it.
"""

from __future__ import annotations

from app.evaluation.dataset import (
    CorpusDocument,
    EvaluationDataset,
    EvaluationQuestion,
    RelevanceLabel,
)
from app.evaluation.metrics import (
    RetrievalScore,
    citation_precision,
    citation_recall,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_retrieval,
)
from app.evaluation.report import (
    AnswerAggregate,
    EvaluationReport,
    LatencyAggregate,
    QuestionReport,
    RetrievalAggregate,
)

__all__ = [
    "AnswerAggregate",
    "CorpusDocument",
    "EvaluationDataset",
    "EvaluationQuestion",
    "EvaluationReport",
    "LatencyAggregate",
    "QuestionReport",
    "RelevanceLabel",
    "RetrievalAggregate",
    "RetrievalScore",
    "citation_precision",
    "citation_recall",
    "hit_at_k",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "score_retrieval",
]
