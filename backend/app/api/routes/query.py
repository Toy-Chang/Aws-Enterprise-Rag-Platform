"""Query endpoint: ask a question about a knowledge base."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import (
    AnswerModelDep,
    EmbedderDep,
    RerankerDep,
    SessionDep,
    SettingsDep,
    VectorStoreDep,
)
from app.core.context import get_request_id
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query import QueryService

router = APIRouter(prefix="/knowledge-bases", tags=["query"])


@router.post(
    "/{knowledge_base_id}/query",
    summary="Ask a question about a knowledge base",
)
def query_knowledge_base(
    knowledge_base_id: str,
    payload: QueryRequest,
    session: SessionDep,
    settings: SettingsDep,
    embedder: EmbedderDep,
    vector_store: VectorStoreDep,
    reranker: RerankerDep,
    answer_model: AnswerModelDep,
) -> QueryResponse:
    """Answer a question from one knowledge base, with the evidence it used.

    The response carries the answer, the passages it was built from and a trace of the
    stages that produced it. When nothing in the knowledge base clears the similarity
    threshold the outcome is ``insufficient_evidence`` and the answer is ``null``: the
    platform reports missing evidence instead of answering from a model's own knowledge.

    The answer is not cached. Two identical questions are two retrievals, which keeps
    the trace honest and leaves caching to the layer that can measure whether it helps.
    """
    result = QueryService(
        session=session,
        embedder=embedder,
        vector_store=vector_store,
        reranker=reranker,
        answer_model=answer_model,
        settings=settings,
    ).answer(
        knowledge_base_id,
        payload.question,
        top_k=payload.top_k,
        min_score=payload.min_score,
    )
    return QueryResponse.from_result(result, request_id=get_request_id())
