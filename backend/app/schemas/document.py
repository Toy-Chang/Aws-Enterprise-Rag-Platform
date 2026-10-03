"""Document request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentRead(BaseModel):
    """Metadata for a stored document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    knowledge_base_id: str
    name: str
    content_type: str | None
    size_bytes: int
    status: DocumentStatus
    version: int
    created_at: datetime
    updated_at: datetime
