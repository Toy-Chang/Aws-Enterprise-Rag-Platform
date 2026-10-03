"""Tests for the evaluation dataset and the rules it enforces.

A dataset that cannot be scored is rejected before any work happens. Scoring it anyway
would turn a broken label into a quality claim, which is the one thing an evaluation must
never do.
"""

from __future__ import annotations

import pytest

from app.core.errors import InvalidEvaluationDatasetError
from app.evaluation import (
    CorpusDocument,
    EvaluationDataset,
    EvaluationQuestion,
    RelevanceLabel,
)

DOCUMENT = CorpusDocument(
    name="policy.md", content="# Policy\n\nCredentials rotate every ninety days."
)
LABEL = RelevanceLabel(document="policy.md", contains="rotate every ninety days")
ANSWERABLE = EvaluationQuestion(id="q1", question="How often?", answerable=True, relevant=(LABEL,))
UNANSWERABLE = EvaluationQuestion(
    id="q2", question="What is the holiday schedule?", answerable=False, relevant=()
)


def build(**overrides: object) -> EvaluationDataset:
    payload: dict[str, object] = {
        "name": "sample",
        "documents": [DOCUMENT],
        "questions": [ANSWERABLE],
    }
    payload.update(overrides)
    return EvaluationDataset.create(**payload)  # type: ignore[arg-type]


def test_a_well_formed_dataset_is_accepted() -> None:
    dataset = build()

    assert dataset.name == "sample"
    assert [document.name for document in dataset.documents] == ["policy.md"]
    assert [question.id for question in dataset.questions] == ["q1"]


def test_an_unanswerable_question_is_allowed_alongside_answerable_ones() -> None:
    dataset = build(questions=[ANSWERABLE, UNANSWERABLE])

    assert [question.answerable for question in dataset.questions] == [True, False]


def test_a_dataset_may_be_entirely_unanswerable() -> None:
    assert build(questions=[UNANSWERABLE]).questions[0].answerable is False


def test_the_name_is_stripped() -> None:
    assert build(name="  sample  ").name == "sample"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"name": "   "}, "needs a name"),
        ({"documents": []}, "at least one document"),
        ({"questions": []}, "at least one question"),
        ({"documents": [DOCUMENT, DOCUMENT]}, "must be unique"),
        ({"documents": [CorpusDocument(name="policy.md", content="   ")]}, "has no content"),
        ({"documents": [CorpusDocument(name="", content="text")]}, "needs a name"),
        ({"documents": [CorpusDocument(name="policy.docx", content="text")]}, "cannot parse"),
        (
            {
                "questions": [
                    EvaluationQuestion(id="q1", question="  ", answerable=True, relevant=(LABEL,))
                ]
            },
            "has no text",
        ),
        (
            {
                "questions": [
                    EvaluationQuestion(id="", question="How?", answerable=True, relevant=(LABEL,))
                ]
            },
            "needs an id",
        ),
        (
            {
                "questions": [
                    EvaluationQuestion(id="q1", question="How?", answerable=True, relevant=())
                ]
            },
            "answerable but labels nothing",
        ),
        (
            {
                "questions": [
                    EvaluationQuestion(
                        id="q1", question="How?", answerable=False, relevant=(LABEL,)
                    )
                ]
            },
            "unanswerable but labels",
        ),
        (
            {
                "questions": [
                    EvaluationQuestion(
                        id="q1",
                        question="How?",
                        answerable=True,
                        relevant=(RelevanceLabel(document="other.md", contains="text"),),
                    )
                ]
            },
            "not one of the dataset's documents",
        ),
        (
            {
                "questions": [
                    EvaluationQuestion(
                        id="q1",
                        question="How?",
                        answerable=True,
                        relevant=(RelevanceLabel(document="policy.md", contains="   "),),
                    )
                ]
            },
            "empty relevance snippet",
        ),
        ({"questions": [ANSWERABLE, ANSWERABLE]}, "must be unique"),
    ],
)
def test_a_dataset_that_could_not_be_scored_is_rejected(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(InvalidEvaluationDatasetError, match=match):
        build(**overrides)


def test_a_rejection_carries_a_stable_code_and_says_what_is_wrong() -> None:
    with pytest.raises(InvalidEvaluationDatasetError) as raised:
        build(
            questions=[
                EvaluationQuestion(
                    id="q1",
                    question="How?",
                    answerable=True,
                    relevant=(RelevanceLabel(document="other.md", contains="text"),),
                )
            ]
        )

    assert raised.value.status_code == 422
    assert raised.value.code == "INVALID_EVALUATION_DATASET"
    assert raised.value.details == {"question": "q1", "document": "other.md"}


def test_an_unsupported_document_format_lists_what_is_supported() -> None:
    with pytest.raises(InvalidEvaluationDatasetError) as raised:
        build(documents=[CorpusDocument(name="policy.docx", content="text")])

    assert raised.value.details["document"] == "policy.docx"
    assert ".md" in raised.value.details["supported_extensions"]
