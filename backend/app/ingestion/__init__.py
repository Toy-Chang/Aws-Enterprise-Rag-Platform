"""Ingestion: turning stored documents into embedded, citable chunks.

Parsing is format-specific and produces text blocks that carry structural metadata;
chunking turns those blocks into retrieval-sized passages while keeping the metadata
attached.
"""

from __future__ import annotations

from app.ingestion.chunking import ChunkDraft, chunk_document
from app.ingestion.parsers import (
    DocumentParseError,
    ParsedBlock,
    ParsedDocument,
    parse_document,
)

__all__ = [
    "ChunkDraft",
    "DocumentParseError",
    "ParsedBlock",
    "ParsedDocument",
    "chunk_document",
    "parse_document",
]
