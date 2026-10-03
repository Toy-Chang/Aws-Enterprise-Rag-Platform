"""Document parsing: bytes in, text blocks with structure out.

Each parser keeps whatever structural metadata its format provides -- the page for a
PDF, the heading path for Markdown -- because that metadata is what makes a citation
useful rather than decorative.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.logging import get_logger

logger = get_logger(__name__)

_ATX_HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

#: Extensions this module can parse, mapped to the parser name reported in metadata.
PARSERS: Final[dict[str, str]] = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}


class DocumentParseError(Exception):
    """Raised when a document cannot be turned into text."""


@dataclass(frozen=True)
class ParsedBlock:
    """A contiguous run of text together with the structure around it."""

    text: str
    page_number: int | None = None
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    """Extracted text plus what the parser noticed while extracting it."""

    blocks: tuple[ParsedBlock, ...]
    parser: str
    notes: tuple[str, ...] = ()


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    """Parse ``content`` according to the extension of ``filename``."""
    suffix = Path(filename).suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        raise DocumentParseError(f"no parser is registered for {suffix or 'this file type'}")

    if parser == "pdf":
        return _parse_pdf(content)
    if parser == "markdown":
        return _parse_markdown(content)
    return _parse_text(content)


def _parse_text(content: bytes) -> ParsedDocument:
    text, notes = _decode(content)
    return ParsedDocument(blocks=(ParsedBlock(text=text),), parser="text", notes=notes)


def _parse_markdown(content: bytes) -> ParsedDocument:
    """Split Markdown on its headings and record the heading path of each block.

    Markdown syntax is otherwise left as written: building a real CommonMark tree
    would mean parsing inline markup to then throw it away, and the raw text is what
    the author wrote. The one exception is a heading line, whose ``#`` markers are
    dropped so that they do not end up as noise in an embedding.
    """
    text, notes = _decode(content)
    blocks: list[ParsedBlock] = []
    heading_path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            blocks.append(ParsedBlock(text="\n".join(buffer), heading_path=tuple(heading_path)))
            buffer.clear()

    for line in text.splitlines():
        match = _ATX_HEADING.match(line)
        if match is None:
            buffer.append(line)
            continue

        flush()
        level = len(match.group(1))
        title = match.group(2)
        # Slicing at level - 1 keeps a jump from h1 to h3 from inventing a parent.
        heading_path[level - 1 :] = [title]
        buffer.append(title)

    flush()
    return ParsedDocument(
        blocks=tuple(blocks), parser="markdown", notes=notes or _markdown_notes(text)
    )


def _markdown_notes(text: str) -> tuple[str, ...]:
    """Report Markdown the parser deliberately did not interpret."""
    if "```" in text:
        return ("fenced code blocks are kept as text",)
    return ()


def _parse_pdf(content: bytes) -> ParsedDocument:
    """Extract one block per page.

    ``pypdf`` raises a range of exception types for malformed files, so the broad
    handler is deliberate: every one of them means the same thing to the caller.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise DocumentParseError("the PDF is encrypted and cannot be read")
        pages = [
            (number, page.extract_text() or "") for number, page in enumerate(reader.pages, start=1)
        ]
    except DocumentParseError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DocumentParseError(f"the PDF could not be read ({type(exc).__name__})") from exc

    blocks = tuple(
        ParsedBlock(text=text, page_number=number) for number, text in pages if text.strip()
    )
    blank_pages = [number for number, text in pages if not text.strip()]
    notes = (f"{len(blank_pages)} page(s) contained no extractable text",) if blank_pages else ()
    return ParsedDocument(blocks=blocks, parser="pdf", notes=notes)


def _decode(content: bytes) -> tuple[str, tuple[str, ...]]:
    """Decode bytes as UTF-8, reporting rather than hiding replacement."""
    try:
        return content.decode("utf-8"), ()
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace"), (
            "the file is not valid UTF-8; undecodable bytes were replaced",
        )
