"""Tests for the answer generation port and its local adapter."""

from __future__ import annotations

import pytest

from app.rag import (
    AnswerModel,
    AnswerRequest,
    ExtractiveAnswerModel,
    GeneratedAnswer,
    Passage,
)


def _passage(chunk_id: str, content: str) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        document_id="doc-1",
        document_name="policy.md",
        chunk_index=0,
        content=content,
        page_number=None,
        heading_path=(),
        score=0.5,
    )


def _request(*passages: Passage) -> AnswerRequest:
    return AnswerRequest(
        question="How often do credentials rotate?",
        context="[1] policy.md\nEvery ninety days.",
        passages=passages,
    )


def test_the_extractive_model_satisfies_its_port() -> None:
    assert isinstance(ExtractiveAnswerModel(), AnswerModel)


def test_the_extractive_model_numbers_the_passages_it_was_given() -> None:
    answer = ExtractiveAnswerModel().answer(
        _request(_passage("a", "First passage."), _passage("b", "Second passage."))
    )

    assert answer.text == "[1] First passage.\n\n[2] Second passage."


def test_the_extractive_model_reports_no_token_usage() -> None:
    answer = ExtractiveAnswerModel().answer(_request(_passage("a", "Text.")))

    assert answer.input_tokens is None
    assert answer.output_tokens is None


def test_the_extractive_model_declares_that_it_does_not_generate() -> None:
    assert ExtractiveAnswerModel().kind == "extractive"
    assert ExtractiveAnswerModel().name == "extractive-local"


def test_the_extractive_model_returns_stored_text_verbatim() -> None:
    stored = "  Credentials rotate every ninety days.  "

    answer = ExtractiveAnswerModel().answer(_request(_passage("a", stored)))

    assert answer.text == "[1] Credentials rotate every ninety days."
    assert stored.strip() in answer.text


def test_the_extractive_model_refuses_to_answer_without_passages() -> None:
    with pytest.raises(ValueError, match="at least one passage"):
        ExtractiveAnswerModel().answer(_request())


def test_a_generated_answer_defaults_to_no_usage() -> None:
    answer = GeneratedAnswer(text="text")

    assert answer.input_tokens is None
    assert answer.output_tokens is None
