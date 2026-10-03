"""End-to-end tests for the query pipeline: retrieval, threshold, answer, trace."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import GenerationFailedError
from app.main import create_app
from app.rag import AnswerRequest, GeneratedAnswer
from tests.api.support import (
    KB_BASE,
    POLICY_MD,
    ask,
    chunks_url,
    document_url,
    long_document,
    upload,
)


class _StubGenerator:
    """Stands in for a hosted model: records what it was asked, returns a fixed answer."""

    name = "stub-model"
    kind = "generated"

    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[AnswerRequest] = []
        self._error = error

    def answer(self, request: AnswerRequest) -> GeneratedAnswer:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return GeneratedAnswer("[1] A generated answer.", input_tokens=128, output_tokens=9)


@pytest.fixture
def indexed_document(client: TestClient, ingest_pending, knowledge_base_id: str) -> dict[str, Any]:
    """A knowledge base holding one ingested document, ready to be queried."""
    document = upload(client, knowledge_base_id, "policy.md", POLICY_MD)
    assert ingest_pending() == 1

    metadata = client.get(document_url(knowledge_base_id, document["id"])).json()
    assert metadata["status"] == "ready"
    return document


def test_an_answer_cites_the_passages_it_was_built_from(
    client: TestClient, indexed_document: dict[str, Any]
) -> None:
    body = ask(
        client, indexed_document["knowledge_base_id"], "How often do database credentials rotate?"
    )

    assert body["outcome"] == "answered"
    assert body["knowledge_base_id"] == indexed_document["knowledge_base_id"]
    assert body["answer"].startswith("[1] ")
    assert body["answer_kind"] == "extractive"
    assert body["usage"] == {"input_tokens": None, "output_tokens": None}

    first = body["citations"][0]
    assert first["marker"] == 1
    assert first["document_id"] == indexed_document["id"]
    assert first["document_name"] == "policy.md"
    assert first["heading_path"] == ["Encryption policy", "Credential rotation"]
    assert first["page_number"] is None
    assert first["rerank_score"] is None
    assert first["score"] > 0
    assert "ninety days" in first["snippet"]


def test_the_local_answer_quotes_stored_text_verbatim(
    client: TestClient, indexed_document: dict[str, Any]
) -> None:
    knowledge_base_id = indexed_document["knowledge_base_id"]
    stored = {
        chunk["id"]: chunk["content"].strip()
        for chunk in client.get(chunks_url(knowledge_base_id, indexed_document["id"])).json()
    }

    body = ask(client, knowledge_base_id, "How often do database credentials rotate?")

    assert body["citations"]
    for citation in body["citations"]:
        assert stored[citation["chunk_id"]] in body["answer"]


def test_the_trace_reports_the_stages_that_ran(
    client: TestClient, indexed_document: dict[str, Any]
) -> None:
    body = ask(
        client, indexed_document["knowledge_base_id"], "How often do database credentials rotate?"
    )

    trace = body["trace"]
    assert trace["retrieval"]["candidates"] >= 1
    assert trace["retrieval"]["above_threshold"] >= 1
    assert trace["retrieval"]["used"] == len(body["citations"])
    assert trace["retrieval"]["top_k"] == 5
    assert trace["retrieval"]["min_score"] == 0.1
    assert trace["retrieval"]["reranked"] is False
    assert trace["retrieval"]["reranker"] is None
    assert trace["retrieval"]["missing_chunks"] == 0
    assert trace["retrieval"]["duration_ms"] >= 0

    assert trace["context"]["passages"] == len(body["citations"])
    assert trace["context"]["chars"] > 0
    assert trace["context"]["skipped"] == 0
    assert trace["context"]["truncated"] is False

    assert trace["generation"]["model"] == "extractive-local"
    assert trace["generation"]["kind"] == "extractive"
    assert trace["generation"]["duration_ms"] >= 0
    assert trace["total_duration_ms"] >= 0
    assert isinstance(trace["request_id"], str)


def test_the_request_id_is_reported_in_the_trace(
    client: TestClient, indexed_document: dict[str, Any]
) -> None:
    response = client.post(
        f"{KB_BASE}/{indexed_document['knowledge_base_id']}/query",
        json={"question": "credentials rotate"},
        headers={"X-Request-ID": "trace-me"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-me"
    assert response.json()["trace"]["request_id"] == "trace-me"


def test_a_generated_answer_reports_its_usage_and_receives_the_marked_context(
    client: TestClient, app: FastAPI, indexed_document: dict[str, Any]
) -> None:
    generator = _StubGenerator()
    app.state.answer_model = generator

    body = ask(
        client, indexed_document["knowledge_base_id"], "How often do database credentials rotate?"
    )

    assert body["answer"] == "[1] A generated answer."
    assert body["answer_kind"] == "generated"
    assert body["usage"] == {"input_tokens": 128, "output_tokens": 9}
    assert body["trace"]["generation"] == {
        "model": "stub-model",
        "kind": "generated",
        "duration_ms": body["trace"]["generation"]["duration_ms"],
    }

    request = generator.requests[0]
    assert request.question == "How often do database credentials rotate?"
    assert request.context.startswith("[1] policy.md — Encryption policy › Credential rotation")
    assert len(request.passages) == len(body["citations"])


def test_a_failing_generator_is_reported_as_a_gateway_error(
    client: TestClient, app: FastAPI, indexed_document: dict[str, Any]
) -> None:
    app.state.answer_model = _StubGenerator(error=GenerationFailedError("upstream refused"))

    response = client.post(
        f"{KB_BASE}/{indexed_document['knowledge_base_id']}/query",
        json={"question": "How often do database credentials rotate?"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GENERATION_FAILED"


def test_a_knowledge_base_with_nothing_ingested_has_no_evidence(
    client: TestClient, knowledge_base_id: str
) -> None:
    body = ask(client, knowledge_base_id, "How often do database credentials rotate?")

    assert body["outcome"] == "insufficient_evidence"
    assert body["answer"] is None
    assert body["answer_kind"] is None
    assert body["citations"] == []
    assert body["usage"] == {"input_tokens": None, "output_tokens": None}
    assert body["trace"]["retrieval"]["candidates"] == 0
    assert body["trace"]["context"]["chars"] == 0
    assert body["trace"]["generation"] is None


def test_a_relevance_threshold_can_reject_every_candidate(
    client: TestClient, indexed_document: dict[str, Any]
) -> None:
    knowledge_base_id = indexed_document["knowledge_base_id"]
    question = "How do I book a desk in the Berlin office?"

    permissive = ask(client, knowledge_base_id, question, min_score=0.0)
    strict = ask(client, knowledge_base_id, question, min_score=0.9)

    assert permissive["outcome"] == "answered"
    assert strict["outcome"] == "insufficient_evidence"
    assert strict["answer"] is None
    assert strict["citations"] == []
    assert strict["trace"]["retrieval"]["candidates"] >= 1
    assert strict["trace"]["retrieval"]["above_threshold"] == 0
    assert strict["trace"]["retrieval"]["min_score"] == 0.9
    assert strict["trace"]["generation"] is None


def test_a_document_that_failed_ingestion_is_not_citable(
    client: TestClient, ingest_pending, knowledge_base_id: str
) -> None:
    upload(client, knowledge_base_id, "broken.pdf", b"definitely not a PDF")
    assert ingest_pending() == 1

    body = ask(client, knowledge_base_id, "definitely a PDF", min_score=0.0)

    assert body["outcome"] == "insufficient_evidence"
    assert body["trace"]["retrieval"]["candidates"] == 0


def test_an_unknown_knowledge_base_is_not_found(client: TestClient) -> None:
    response = client.post(f"{KB_BASE}/does-not-exist/query", json={"question": "anything"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_a_question_outside_the_allowed_shape_is_rejected(
    client: TestClient, knowledge_base_id: str, question: str
) -> None:
    response = client.post(f"{KB_BASE}/{knowledge_base_id}/query", json={"question": question})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"


def test_top_k_limits_the_number_of_citations(
    client: TestClient, ingest_pending, knowledge_base_id: str
) -> None:
    upload(client, knowledge_base_id, "manual.md", long_document())
    assert ingest_pending() == 1
    question = "procedure1 procedure2 procedure3 procedure4"

    everything = ask(client, knowledge_base_id, question, top_k=10)
    limited = ask(client, knowledge_base_id, question, top_k=2)

    assert len(everything["citations"]) >= 4
    # Retrieval selects passages and the context budget decides how many of them the
    # answer can cite, so the two counts are reported separately.
    assert everything["trace"]["retrieval"]["used"] >= len(everything["citations"])
    assert everything["trace"]["context"]["passages"] == len(everything["citations"])
    assert len(limited["citations"]) == 2
    # The candidate pool is bounded by the request: without a reranker, retrieval asks
    # the index for exactly as many passages as the caller wants back.
    assert limited["trace"]["retrieval"]["candidates"] == 2
    assert limited["trace"]["retrieval"]["used"] == 2
    assert limited["trace"]["retrieval"]["top_k"] == 2
    assert [citation["marker"] for citation in limited["citations"]] == [1, 2]


def test_the_context_budget_bounds_what_the_generator_reads(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"context_max_chars": 80}))

    with TestClient(app) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Tight"}).json()["id"]
        upload(client, knowledge_base_id, "policy.md", POLICY_MD)
        assert app.state.ingestion.run_pending() == 1

        body = ask(client, knowledge_base_id, "encrypted credentials rotate")

    context = body["trace"]["context"]
    assert context["truncated"] is True
    assert context["passages"] == 1
    assert context["skipped"] >= 1
    assert context["chars"] == 80
    assert len(body["citations"]) == 1


def test_reranking_widens_the_candidate_pool_and_is_reported(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"rerank_enabled": True}))

    with TestClient(app) as client:
        knowledge_base_id = client.post(KB_BASE, json={"name": "Reranked"}).json()["id"]
        upload(client, knowledge_base_id, "policy.md", POLICY_MD)
        assert app.state.ingestion.run_pending() == 1

        body = ask(
            client,
            knowledge_base_id,
            "How often do database credentials rotate?",
            top_k=1,
        )

    retrieval = body["trace"]["retrieval"]
    assert retrieval["reranked"] is True
    assert retrieval["reranker"] == "lexical-overlap"
    # One passage is returned, but more than one was scored: that is what the reranker
    # needs in order to have a choice.
    assert retrieval["used"] == 1
    assert retrieval["candidates"] > 1
    assert len(body["citations"]) == 1
    assert body["citations"][0]["rerank_score"] is not None
