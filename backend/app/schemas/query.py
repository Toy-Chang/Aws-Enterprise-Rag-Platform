"""Query request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.query import QueryOutcome, QueryResult


class QueryRequest(BaseModel):
    """A question asked of one knowledge base."""

    question: str = Field(
        min_length=1,
        max_length=2000,
        description="The question to answer from the knowledge base.",
        examples=["How often do database credentials rotate?"],
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Passages to retrieve and answer from; defaults to the service setting.",
    )
    min_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description=(
            "Similarity below which a passage is not treated as evidence. Raising it "
            "makes the platform report insufficient evidence sooner."
        ),
    )

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question must not be blank")
        return question


class CitationRead(BaseModel):
    """A passage the answer was built from."""

    marker: int = Field(description="The marker this passage carries in the answer.")
    document_id: str
    document_name: str
    chunk_id: str
    chunk_index: int
    page_number: int | None
    heading_path: list[str]
    score: float = Field(description="Similarity reported by the vector index.")
    rerank_score: float | None = Field(
        default=None, description="Second-stage score, when a reranker ran."
    )
    snippet: str = Field(description="The opening of the passage, for display.")


class UsageRead(BaseModel):
    """Token usage, when the generator reports it."""

    input_tokens: int | None
    output_tokens: int | None


class RetrievalTrace(BaseModel):
    """What retrieval did for this query.

    The counts describe this call, not the knowledge base: ``candidates`` is bounded by
    the requested ``top_k`` (multiplied by the candidate pool when a reranker runs), so
    a small ``top_k`` reports a small candidate count even in a large corpus.
    """

    candidates: int = Field(description="Passages the index returned for this query.")
    above_threshold: int = Field(description="Passages that cleared the threshold.")
    used: int = Field(
        description=(
            "Passages retrieval selected. The context budget can still keep some of "
            "them out of the answer, which ``context.passages`` reports."
        )
    )
    top_k: int
    min_score: float
    reranked: bool
    reranker: str | None
    missing_chunks: int = Field(
        description="Matches whose chunk had already been deleted; should be zero."
    )
    duration_ms: float


class ContextTrace(BaseModel):
    """How much of the retrieval reached the generator."""

    chars: int
    passages: int
    skipped: int = Field(description="Passages dropped because the budget was exhausted.")
    truncated: bool = Field(description="Whether the first passage alone exceeded the budget.")


class GenerationTrace(BaseModel):
    """Which generator ran, and how long it took."""

    model: str
    kind: str = Field(description="'extractive' or 'generated'.")
    duration_ms: float


class QueryTrace(BaseModel):
    """The stages behind one answer, for debugging and for the UI."""

    request_id: str | None
    retrieval: RetrievalTrace
    context: ContextTrace
    generation: GenerationTrace | None
    total_duration_ms: float


class QueryResponse(BaseModel):
    """An answer, the evidence behind it, and a trace of how it was produced."""

    knowledge_base_id: str
    question: str
    outcome: QueryOutcome = Field(
        description=(
            "'answered' when evidence was found, otherwise 'insufficient_evidence', in "
            "which case the answer is null."
        )
    )
    answer: str | None
    answer_kind: str | None = Field(
        default=None,
        description="'extractive' for passages returned verbatim, 'generated' for a model.",
    )
    citations: list[CitationRead]
    usage: UsageRead
    trace: QueryTrace

    @classmethod
    def from_result(cls, result: QueryResult, *, request_id: str | None) -> QueryResponse:
        """Build the response body from a query result."""
        return cls(
            knowledge_base_id=result.knowledge_base_id,
            question=result.question,
            outcome=result.outcome,
            answer=result.answer,
            answer_kind=result.answer_kind,
            citations=[
                CitationRead(
                    marker=citation.marker,
                    document_id=citation.document_id,
                    document_name=citation.document_name,
                    chunk_id=citation.chunk_id,
                    chunk_index=citation.chunk_index,
                    page_number=citation.page_number,
                    heading_path=list(citation.heading_path),
                    score=citation.score,
                    rerank_score=citation.rerank_score,
                    snippet=citation.snippet,
                )
                for citation in result.citations
            ],
            usage=UsageRead(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            ),
            trace=QueryTrace(
                request_id=request_id,
                retrieval=RetrievalTrace(
                    candidates=result.retrieval.candidates,
                    above_threshold=result.retrieval.above_threshold,
                    used=len(result.retrieval.passages),
                    top_k=result.retrieval.top_k,
                    min_score=result.retrieval.min_score,
                    reranked=result.retrieval.reranked,
                    reranker=result.retrieval.reranker,
                    missing_chunks=result.retrieval.missing_chunks,
                    duration_ms=result.retrieval.duration_ms,
                ),
                context=ContextTrace(
                    chars=result.context.chars,
                    passages=result.context.passages,
                    skipped=result.context.skipped,
                    truncated=result.context.truncated,
                ),
                generation=(
                    GenerationTrace(
                        model=result.generation.model,
                        kind=result.generation.kind,
                        duration_ms=result.generation.duration_ms,
                    )
                    if result.generation is not None
                    else None
                ),
                total_duration_ms=result.total_duration_ms,
            ),
        )
