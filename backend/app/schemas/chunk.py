"""Chunk response schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChunkRead(BaseModel):
    """One indexed passage of a document.

    Offsets are relative to the normalised text of the block the passage came from,
    and ``page_number`` and ``heading_path`` are the structure that enclosed it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    chunk_index: int
    content: str
    char_start: int
    char_end: int
    page_number: int | None
    heading_path: list[str]
    created_at: datetime
