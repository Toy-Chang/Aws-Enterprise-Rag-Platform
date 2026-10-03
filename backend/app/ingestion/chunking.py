"""Structure-preserving chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.ingestion.parsers import ParsedDocument

#: Preferred cut points, longest first, so a window ends at a paragraph or a line
#: rather than in the middle of a sentence when there is a choice.
_BOUNDARIES: Final[tuple[str, ...]] = ("\n\n", "\n", ". ", " ")

_BLANK_RUN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
_TRAILING_SPACES: Final[re.Pattern[str]] = re.compile(r"[ \t]+\n")


@dataclass(frozen=True)
class ChunkDraft:
    """A chunk before it is stored or embedded.

    ``char_start`` and ``char_end`` are offsets into the normalised text of the block
    the chunk came from, not into the original file, so they stay meaningful across
    formats and encodings.
    """

    index: int
    content: str
    char_start: int
    char_end: int
    page_number: int | None
    heading_path: tuple[str, ...]


def normalise(text: str) -> str:
    """Collapse whitespace that would otherwise consume the chunk budget."""
    collapsed = _BLANK_RUN.sub("\n\n", _TRAILING_SPACES.sub("\n", text))
    return collapsed.strip()


def chunk_document(
    document: ParsedDocument, *, chunk_size: int, chunk_overlap: int
) -> list[ChunkDraft]:
    """Split every block of ``document`` into overlapping windows.

    Sizes are counted in characters, not in model tokens. Counting tokens needs the
    tokenizer of the model that will consume the text, which is a property of the
    generation adapter; the approximation is recorded here rather than hidden.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    drafts: list[ChunkDraft] = []
    for block in document.blocks:
        text = normalise(block.text)
        if not text:
            continue
        for start, end in _windows(text, size=chunk_size, overlap=chunk_overlap):
            raw = text[start:end]
            content = raw.strip()
            if not content:
                continue
            # Trim the offsets by the whitespace that strip() removed, so that
            # char_start/char_end continue to bound the stored content exactly.
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            drafts.append(
                ChunkDraft(
                    index=len(drafts),
                    content=content,
                    char_start=start + leading,
                    char_end=end - trailing,
                    page_number=block.page_number,
                    heading_path=block.heading_path,
                )
            )
    return drafts


def _windows(text: str, *, size: int, overlap: int) -> list[tuple[int, int]]:
    """Return the (start, end) offsets of the chunk windows over ``text``."""
    windows: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = _window_end(text, start, size)
        windows.append((start, end))
        if end >= length:
            break
        # Overlapping keeps a sentence that straddles a boundary retrievable from
        # both sides. The maximum guarantees progress even when overlap is large
        # relative to the remaining text.
        start = max(end - overlap, start + 1)
    return windows


def _window_end(text: str, start: int, size: int) -> int:
    """Choose where the window that begins at ``start`` should end.

    A boundary is only accepted in the second half of the window; accepting the first
    one it finds anywhere would produce windows far smaller than the configured size.
    """
    limit = min(start + size, len(text))
    if limit >= len(text):
        return len(text)

    floor = start + size // 2
    for boundary in _BOUNDARIES:
        index = text.rfind(boundary, floor, limit)
        if index != -1:
            return index + len(boundary)
    return limit
