"""Tests for the retrieved-passage value object."""

from __future__ import annotations

from app.rag import Passage


def _passage(**overrides: object) -> Passage:
    values: dict[str, object] = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "document_name": "policy.md",
        "chunk_index": 0,
        "content": "text",
        "page_number": None,
        "heading_path": (),
        "score": 0.5,
    }
    values.update(overrides)
    return Passage(**values)  # type: ignore[arg-type]


def test_a_passage_without_structure_is_labelled_by_its_document() -> None:
    assert _passage().label == "policy.md"


def test_a_heading_path_is_rendered_as_a_trail() -> None:
    passage = _passage(heading_path=("Encryption policy", "Credential rotation"))

    assert passage.label == "policy.md — Encryption policy › Credential rotation"


def test_a_page_number_is_reported_alongside_the_heading() -> None:
    passage = _passage(page_number=7, heading_path=("Rotation",))

    assert passage.label == "policy.md — Rotation (page 7)"


def test_a_page_number_without_headings_is_reported_on_its_own() -> None:
    assert _passage(page_number=2).label == "policy.md — page 2"


def test_a_rerank_score_is_attached_without_mutating_the_original() -> None:
    passage = _passage()

    scored = passage.scored_by_reranker(0.75)

    assert scored.rerank_score == 0.75
    assert scored.chunk_id == passage.chunk_id
    assert passage.rerank_score is None
