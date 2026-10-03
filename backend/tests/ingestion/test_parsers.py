"""Tests for the format parsers."""

from __future__ import annotations

import pytest

from app.ingestion import DocumentParseError, parse_document
from tests.ingestion.pdf_builder import build_pdf

MARKDOWN = b"""# Encryption

Customer data is encrypted at rest.

## Key management

Keys live in KMS.

### Rotation

Rotate every ninety days.
"""


def test_text_becomes_a_single_block() -> None:
    parsed = parse_document("notes.txt", b"line one\nline two\n")

    assert parsed.parser == "text"
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].text == "line one\nline two\n"
    assert parsed.blocks[0].page_number is None
    assert parsed.blocks[0].heading_path == ()
    assert parsed.notes == ()


def test_markdown_records_the_heading_path_of_each_block() -> None:
    parsed = parse_document("policy.md", MARKDOWN)

    assert parsed.parser == "markdown"
    assert [block.heading_path for block in parsed.blocks] == [
        ("Encryption",),
        ("Encryption", "Key management"),
        ("Encryption", "Key management", "Rotation"),
    ]


def test_markdown_heading_markers_are_dropped_from_the_text() -> None:
    parsed = parse_document("policy.md", MARKDOWN)

    assert parsed.blocks[0].text.startswith("Encryption\n")
    assert "##" not in parsed.blocks[1].text


def test_markdown_text_before_the_first_heading_has_no_heading_path() -> None:
    parsed = parse_document("policy.md", b"Preamble text.\n\n# First heading\n\nBody.\n")

    assert parsed.blocks[0].heading_path == ()
    assert "Preamble text." in parsed.blocks[0].text


def test_markdown_heading_jumps_do_not_invent_parents() -> None:
    parsed = parse_document("policy.md", b"# Top\n\n### Deep\n\nBody.\n")

    assert parsed.blocks[1].heading_path == ("Top", "Deep")


def test_markdown_reports_that_code_fences_are_kept_as_text() -> None:
    parsed = parse_document("policy.md", b"# Title\n\n```\nmake deploy\n```\n")

    assert parsed.notes == ("fenced code blocks are kept as text",)
    assert "make deploy" in parsed.blocks[0].text


def test_pdf_pages_become_blocks_carrying_their_page_number() -> None:
    content = build_pdf(["First page text.", "Second page text."])

    parsed = parse_document("manual.pdf", content)

    assert parsed.parser == "pdf"
    assert [(block.page_number, block.text) for block in parsed.blocks] == [
        (1, "First page text."),
        (2, "Second page text."),
    ]
    assert parsed.notes == ()


def test_pdf_pages_without_text_are_skipped_and_reported() -> None:
    content = build_pdf(["Only page with text.", ""])

    parsed = parse_document("manual.pdf", content)

    assert [block.page_number for block in parsed.blocks] == [1]
    assert parsed.notes == ("1 page(s) contained no extractable text",)


def test_a_corrupt_pdf_raises_a_parse_error() -> None:
    with pytest.raises(DocumentParseError, match="could not be read"):
        parse_document("manual.pdf", b"this is not a PDF at all")


@pytest.mark.parametrize("filename", ["archive.docx", "sheet.xlsx", "noextension"])
def test_an_unknown_extension_raises_a_parse_error(filename: str) -> None:
    with pytest.raises(DocumentParseError):
        parse_document(filename, b"content")


def test_invalid_utf8_is_replaced_and_reported() -> None:
    parsed = parse_document("notes.txt", b"caf\xe9 au lait")

    assert parsed.notes == ("the file is not valid UTF-8; undecodable bytes were replaced",)
    assert "caf\ufffd" in parsed.blocks[0].text
