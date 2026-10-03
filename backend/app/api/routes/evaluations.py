"""Evaluation endpoint: score the pipeline against labelled questions."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import (
    AnswerModelDep,
    EmbedderDep,
    IngestionDep,
    MetricsDep,
    RerankerDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    VectorStoreDep,
)
from app.schemas.evaluation import EvaluationRequest, EvaluationResponse
from app.services.evaluation import EvaluationService

router = APIRouter(tags=["evaluation"])


@router.post("/evaluations", summary="Run a labelled dataset through the pipeline and score it")
def run_evaluation(
    payload: EvaluationRequest,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    vector_store: VectorStoreDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    answer_model: AnswerModelDep,
    ingestion: IngestionDep,
    metrics: MetricsDep,
) -> EvaluationResponse:
    """Ingest a corpus, ask every question of the dataset, and score what came back.

    The dataset carries its own corpus, so a run does not depend on what is already
    ingested: the corpus goes into a temporary knowledge base, which is removed before the
    response is returned. The questions are asked through the same pipeline the query
    endpoint serves, with the same settings, so what is measured is what a caller gets.

    What the metrics mean, and what they do not: ``recall_at_k``, ``precision_at_k``,
    ``hit_rate_at_k``, ``mrr`` and ``ndcg_at_k`` are standard information-retrieval
    measures computed from the labels the caller supplied, where ``precision_at_k``
    divides by ``k`` by convention. ``citation_precision`` and ``citation_recall`` ask
    whether the chunks the answer cited are the ones the labels mark relevant, which says
    nothing about whether the prose is well written. **No faithfulness, groundedness or
    hallucination metric is reported**, because judging an answer's content requires human
    or model judgement and this endpoint has neither; a lexical heuristic standing in for
    it would be a number with no meaning.

    A question the labels cannot score -- an unanswerable one, or one whose snippet matched
    no chunk -- reports ``null`` metrics and appears in ``issues`` instead of being
    averaged in as a zero.
    """
    report = EvaluationService(
        session=session,
        storage=storage,
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        answer_model=answer_model,
        ingestion=ingestion,
        settings=settings,
        metrics=metrics,
    ).run(payload.to_dataset(), k=payload.k, min_score=payload.min_score)
    return EvaluationResponse.from_report(report)
