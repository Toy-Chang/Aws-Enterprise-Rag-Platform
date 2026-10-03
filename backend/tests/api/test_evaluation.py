"""Tests for the evaluation endpoint, end to end.

The sample dataset under ``evaluation/datasets`` is run exactly as committed: it is both
the demonstration of the format and a fixture, so a dataset that stops being runnable fails
the suite instead of misleading a reader.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.api.support import KB_BASE, POLICY_MD

EVALUATIONS_URL = "/api/v1/evaluations"
METRICS_URL = "/api/v1/metrics"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DATASET = REPOSITORY_ROOT / "evaluation" / "datasets" / "sample.json"

GOOD_LABEL = {"document": "policy.md", "contains": "rotate every ninety days"}


def sample_payload() -> dict[str, Any]:
    """The committed sample dataset, as a request body."""
    return json.loads(SAMPLE_DATASET.read_text(encoding="utf-8"))


def inline_payload(
    questions: list[dict[str, Any]],
    *,
    documents: list[dict[str, Any]] | None = None,
    k: int = 5,
) -> dict[str, Any]:
    return {
        "name": "inline",
        "k": k,
        "documents": documents or [{"name": "policy.md", "content": POLICY_MD.decode("utf-8")}],
        "questions": questions,
    }


def evaluate(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(EVALUATIONS_URL, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_sample_dataset_runs_end_to_end(client: TestClient) -> None:
    body = evaluate(client, sample_payload())

    assert body["dataset"] == "platform-runbooks-smoke"
    assert (body["documents"], body["total_questions"]) == (5, 6)
    assert (body["answerable"], body["unanswerable"]) == (5, 1)
    assert body["chunks"] >= 5
    assert body["issues"] == []

    retrieval = body["retrieval"]
    assert retrieval is not None
    assert retrieval["questions"] == 5, "the five labelled questions were scorable"
    for name in ("recall_at_k", "precision_at_k", "hit_rate_at_k", "mrr", "ndcg_at_k"):
        assert 0.0 <= retrieval[name] <= 1.0, name

    answers = body["answers"]
    assert answers["answered"] + answers["insufficient_evidence"] == 6
    # A capability check rather than a quality claim: the sample's questions quote the
    # corpus, so the pipeline has to be able to find what is literally quoted from it. A
    # failure here means retrieval or the dataset broke, not that the model got worse.
    assert answers["answerable_answered"] == 1.0
    # Measured, and deliberately asserted: with the default threshold this dataset's
    # unrelated question is *answered*, because the lexical model scores it 0.3146 while the
    # weakest genuinely relevant question scores 0.2578. No threshold separates them, which
    # is the finding the README records -- a threshold cannot be tuned into a relevance
    # filter for this model. Asserting the measured value means changing the default
    # threshold has to be accompanied by re-measuring, not by quietly editing this line.
    assert answers["unanswerable_abstained"] == 0.0
    for name in ("citation_precision", "citation_recall"):
        assert answers[name] is None or 0.0 <= answers[name] <= 1.0

    # No metric is reported without a denominator.
    assert answers["citation_precision"] is not None, "this dataset does produce citations"

    assert body["latency"]["retrieval_ms"]["count"] == 6
    assert body["latency"]["total_ms"]["count"] == 6

    wanted = {question["id"] for question in sample_payload()["questions"]}
    by_id = {question["id"]: question for question in body["per_question"]}
    assert set(by_id) == wanted
    assert by_id["holiday-schedule"]["outcome"] == "answered"
    assert by_id["holiday-schedule"]["recall_at_k"] is None
    assert by_id["holiday-schedule"]["answer_kind"] == "extractive"
    for question in body["per_question"]:
        assert question["issues"] == []
        if question["answerable"]:
            assert question["relevant_chunks"] >= 1
            assert 0.0 <= question["ndcg_at_k"] <= 1.0


def test_an_unanswerable_question_reports_no_retrieval_metrics(client: TestClient) -> None:
    body = evaluate(client, sample_payload())

    unanswerable = next(question for question in body["per_question"] if not question["answerable"])

    assert unanswerable["recall_at_k"] is None
    assert unanswerable["precision_at_k"] is None
    assert unanswerable["ndcg_at_k"] is None
    assert unanswerable["matched_chunks"] is None
    assert unanswerable["relevant_chunks"] == 0


def test_a_stricter_threshold_buys_abstention_at_the_cost_of_answerable_questions(
    client: TestClient,
) -> None:
    """The tradeoff this endpoint exists to measure, on the sample dataset.

    Measured on the committed sample: the unrelated question's best candidate scores 0.3146
    and the weakest genuinely relevant one scores 0.2578, so 0.35 is inside the only gap
    available. At 0.35 the unrelated question is refused -- and so is the credential-rotation
    question, which is the cost of buying that abstention. No threshold in this range both
    refuses it and keeps every answerable question, which is the point.

    If this fails, the model or the dataset changed: re-measure and record the new numbers
    rather than widening the assertion.
    """
    body = evaluate(client, {**sample_payload(), "min_score": 0.35})

    assert body["min_score"] == 0.35
    assert body["answers"]["unanswerable_abstained"] == 1.0
    assert body["answers"]["answerable_answered"] == 0.8

    by_id = {question["id"]: question for question in body["per_question"]}
    assert by_id["holiday-schedule"]["outcome"] == "insufficient_evidence"
    assert by_id["credential-rotation"]["outcome"] == "insufficient_evidence"
    assert by_id["encryption-at-rest"]["outcome"] == "answered"
    assert by_id["snapshot-retention"]["outcome"] == "answered"


def test_the_threshold_a_run_used_is_reported_with_its_results(client: TestClient) -> None:
    """Numbers produced under a different policy cannot be read without the policy."""
    default_run = evaluate(client, sample_payload())
    strict_run = evaluate(client, {**sample_payload(), "min_score": 0.35})

    assert default_run["min_score"] == 0.1
    assert strict_run["min_score"] == 0.35
    assert default_run["retrieval"]["questions"] == strict_run["retrieval"]["questions"] == 5


def test_the_temporary_corpus_does_not_stay_in_the_platform(
    client: TestClient, storage_dir: Path
) -> None:
    body = evaluate(client, sample_payload())
    temporary_id = body["temporary_knowledge_base_id"]

    assert client.get(f"{KB_BASE}/{temporary_id}").status_code == 404
    assert client.get(KB_BASE).json() == [], "the run left a knowledge base behind"
    assert [path for path in storage_dir.rglob("*") if path.is_file()] == []


def test_a_label_that_matches_no_chunk_is_reported_rather_than_scored(
    client: TestClient,
) -> None:
    body = evaluate(
        client,
        inline_payload(
            [
                {
                    "id": "good",
                    "question": "How often do database credentials rotate?",
                    "answerable": True,
                    "relevant": [GOOD_LABEL],
                },
                {
                    "id": "bogus",
                    "question": "How long is data retained?",
                    "answerable": True,
                    "relevant": [{"document": "policy.md", "contains": "retained for seven years"}],
                },
            ]
        ),
    )

    assert body["retrieval"]["questions"] == 1, "only the question with a resolvable label"
    assert len(body["issues"]) == 1
    assert "retained for seven years" in body["issues"][0]

    by_id = {question["id"]: question for question in body["per_question"]}
    assert by_id["good"]["recall_at_k"] == 1.0
    assert by_id["bogus"]["relevant_chunks"] == 0
    assert by_id["bogus"]["recall_at_k"] is None
    assert by_id["bogus"]["matched_chunks"] is None
    assert by_id["bogus"]["issues"] == ["no chunk of 'policy.md' contains the labelled snippet"]


def test_a_document_that_cannot_be_ingested_is_reported_and_not_raised(
    client: TestClient,
) -> None:
    """A broken corpus is a result about the dataset, not a server error."""
    body = evaluate(
        client,
        inline_payload(
            [
                {
                    "id": "q",
                    "question": "What does the manual say?",
                    "answerable": True,
                    "relevant": [{"document": "broken.pdf", "contains": "anything"}],
                }
            ],
            documents=[{"name": "broken.pdf", "content": "definitely not a PDF"}],
        ),
    )

    assert body["chunks"] == 0
    assert any("did not ingest" in issue for issue in body["issues"])
    assert body["retrieval"] is None
    assert body["answers"]["answered"] == 0
    assert body["answers"]["answerable_answered"] == 0.0
    assert body["per_question"][0]["outcome"] == "insufficient_evidence"


def test_the_same_dataset_can_be_run_twice_and_score_identically(client: TestClient) -> None:
    first = evaluate(client, sample_payload())
    second = evaluate(client, sample_payload())

    assert first["temporary_knowledge_base_id"] != second["temporary_knowledge_base_id"]
    # The local adapters are deterministic, so only the identifiers and the timings differ.
    assert first["retrieval"] == second["retrieval"]
    assert first["answers"] == second["answers"]


def test_an_unanswerable_question_that_labels_evidence_is_rejected(client: TestClient) -> None:
    response = client.post(
        EVALUATIONS_URL,
        json=inline_payload(
            [
                {
                    "id": "q",
                    "question": "How often do credentials rotate?",
                    "answerable": False,
                    "relevant": [GOOD_LABEL],
                }
            ]
        ),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_EVALUATION_DATASET"
    assert body["error"]["details"] == {"question": "q"}
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_a_label_naming_an_undeclared_document_is_rejected(client: TestClient) -> None:
    response = client.post(
        EVALUATIONS_URL,
        json=inline_payload(
            [
                {
                    "id": "q",
                    "question": "How often do credentials rotate?",
                    "answerable": True,
                    "relevant": [{"document": "missing.md", "contains": "rotate"}],
                }
            ]
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_EVALUATION_DATASET"


def test_the_payload_bounds_are_enforced(client: TestClient) -> None:
    valid_question = {
        "id": "q",
        "question": "How often do database credentials rotate?",
        "answerable": True,
        "relevant": [GOOD_LABEL],
    }

    too_many_documents = inline_payload(
        [valid_question],
        documents=[{"name": f"doc{index}.md", "content": "text"} for index in range(26)],
    )
    too_many_questions = inline_payload([valid_question] * 101)

    assert client.post(EVALUATIONS_URL, json=too_many_documents).status_code == 422
    assert client.post(EVALUATIONS_URL, json=too_many_questions).status_code == 422
    assert (
        client.post(EVALUATIONS_URL, json=inline_payload([valid_question], k=0)).status_code == 422
    )
    assert client.post(EVALUATIONS_URL, json={"documents": [], "questions": []}).status_code == 422


def test_an_evaluation_run_is_counted_in_the_metrics(client: TestClient) -> None:
    evaluate(client, sample_payload())

    body = client.get(METRICS_URL).json()

    assert body["counters"]["evaluation.runs"] == 1
    assert body["counters"]["evaluation.questions.total"] == 6
    assert body["latencies"]["evaluation"]["observed"] == 1
    assert body["counters"]["ingestion.succeeded"] == 5
    assert body["counters"]["query.answered"] >= 1
