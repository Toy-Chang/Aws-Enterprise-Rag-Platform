"""Tests for the chunker."""

from __future__ import annotations

import pytest

from app.ingestion import ParsedBlock, ParsedDocument, chunk_document
from app.ingestion.chunking import normalise


def _document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(blocks=blocks, parser="text")


def test_short_text_produces_a_single_chunk() -> None:
    drafts = chunk_document(
        _document(ParsedBlock(text="A short paragraph.")), chunk_size=100, chunk_overlap=10
    )

    assert len(drafts) == 1
    assert drafts[0].index == 0
    assert drafts[0].content == "A short paragraph."


def test_chunks_never_exceed_the_configured_size() -> None:
    document = _document(ParsedBlock(text="word " * 400))

    drafts = chunk_document(document, chunk_size=120, chunk_overlap=30)

    assert len(drafts) > 5
    assert all(len(draft.content) <= 120 for draft in drafts)


def test_offsets_bound_the_stored_content() -> None:
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three, which is longer.\n"
    document = _document(ParsedBlock(text=text))

    drafts = chunk_document(document, chunk_size=40, chunk_overlap=8)
    normalised = normalise(text)

    assert len(drafts) > 1
    for draft in drafts:
        assert normalised[draft.char_start : draft.char_end] == draft.content


def test_consecutive_chunks_overlap() -> None:
    text = "abcdefghij" * 40
    drafts = chunk_document(_document(ParsedBlock(text=text)), chunk_size=100, chunk_overlap=25)
    normalised = normalise(text)

    assert len(drafts) >= 3
    for previous, following in zip(drafts, drafts[1:], strict=False):
        assert following.char_start < previous.char_end
        assert normalised[following.char_start : previous.char_end] in previous.content


def test_a_paragraph_boundary_is_preferred_over_a_hard_cut() -> None:
    text = "A" * 60 + "\n\n" + "B" * 60

    drafts = chunk_document(_document(ParsedBlock(text=text)), chunk_size=100, chunk_overlap=0)

    assert [draft.content for draft in drafts] == ["A" * 60, "B" * 60]


def test_page_and_heading_metadata_are_carried_into_every_chunk() -> None:
    block = ParsedBlock(text="Body text. " * 40, page_number=7, heading_path=("Top", "Sub"))

    drafts = chunk_document(_document(block), chunk_size=150, chunk_overlap=20)

    assert len(drafts) > 1
    assert all(draft.page_number == 7 for draft in drafts)
    assert all(draft.heading_path == ("Top", "Sub") for draft in drafts)


def test_chunk_indexes_are_sequential_across_blocks() -> None:
    drafts = chunk_document(
        _document(
            ParsedBlock(text="First block."),
            ParsedBlock(text="Second block."),
            ParsedBlock(text="Third block."),
        ),
        chunk_size=100,
        chunk_overlap=10,
    )

    assert [draft.index for draft in drafts] == [0, 1, 2]


def test_blocks_without_text_produce_nothing() -> None:
    drafts = chunk_document(
        _document(ParsedBlock(text="   \n\n   "), ParsedBlock(text="Real content.")),
        chunk_size=100,
        chunk_overlap=10,
    )

    assert [draft.content for draft in drafts] == ["Real content."]


def test_a_size_smaller_than_the_overlap_still_terminates() -> None:
    drafts = chunk_document(
        _document(ParsedBlock(text="abcdefghijklmnopqrstuvwxyz")), chunk_size=5, chunk_overlap=4
    )

    assert len(drafts) > 1
    assert all(len(draft.content) <= 5 for draft in drafts)


def test_an_overlap_that_is_not_smaller_than_the_size_is_rejected() -> None:
    document = _document(ParsedBlock(text="content"))

    with pytest.raises(ValueError, match="chunk_overlap"):
        chunk_document(document, chunk_size=100, chunk_overlap=100)


def test_a_non_positive_size_is_rejected() -> None:
    document = _document(ParsedBlock(text="content"))

    with pytest.raises(ValueError, match="chunk_size"):
        chunk_document(document, chunk_size=0, chunk_overlap=0)
