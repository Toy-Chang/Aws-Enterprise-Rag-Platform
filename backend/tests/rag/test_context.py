"""Tests for context and prompt assembly."""

from __future__ import annotations

import pytest

from app.rag import Passage, build_context, build_prompt


def _passage(chunk_id: str, content: str, **overrides: object) -> Passage:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "document_name": "policy.md",
        "chunk_index": 0,
        "content": content,
        "page_number": None,
        "heading_path": (),
        "score": 0.5,
    }
    values.update(overrides)
    return Passage(**values)  # type: ignore[arg-type]


def test_passages_are_numbered_from_one_with_their_source() -> None:
    bundle = build_context(
        [
            _passage("a", "First passage.", heading_path=("Rotation",)),
            _passage("b", "Second passage."),
        ],
        max_chars=1000,
    )

    assert bundle.text.startswith("[1] policy.md — Rotation\nFirst passage.")
    assert "[2] policy.md\nSecond passage." in bundle.text
    assert [passage.chunk_id for passage in bundle.passages] == ["a", "b"]
    assert bundle.skipped == 0
    assert bundle.truncated is False


def test_markers_stay_contiguous_when_a_passage_is_skipped() -> None:
    bundle = build_context(
        [
            _passage("a", "A" * 50),
            _passage("b", "B" * 400),
            _passage("c", "C" * 50),
        ],
        max_chars=140,
    )

    assert [passage.chunk_id for passage in bundle.passages] == ["a", "c"]
    assert bundle.skipped == 1
    assert "[2] policy.md\n" + "C" * 50 in bundle.text
    assert "B" * 10 not in bundle.text


def test_a_first_passage_that_does_not_fit_is_truncated_rather_than_dropped() -> None:
    bundle = build_context([_passage("a", "A" * 500), _passage("b", "B" * 10)], max_chars=60)

    assert bundle.truncated is True
    assert bundle.skipped == 1
    assert len(bundle.text) == 60
    assert [passage.chunk_id for passage in bundle.passages] == ["a"]


def test_no_passages_produce_an_empty_bundle() -> None:
    bundle = build_context([], max_chars=100)

    assert bundle.text == ""
    assert bundle.passages == ()
    assert bundle.skipped == 0


def test_a_non_positive_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        build_context([_passage("a", "text")], max_chars=0)


def test_the_prompt_carries_the_instructions_the_context_and_the_question() -> None:
    prompt = build_prompt("How often do credentials rotate?", "[1] policy.md\nEvery 90 days.")

    assert "only the numbered context passages" in prompt
    assert "Never fall back on knowledge from outside the passages" in prompt
    assert "[1] policy.md\nEvery 90 days." in prompt
    assert prompt.endswith("Question: How often do credentials rotate?\nAnswer:")
