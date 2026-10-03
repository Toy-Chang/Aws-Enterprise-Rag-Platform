"""ORM models.

Importing this package registers every mapped class on the shared metadata, which
is what schema creation and relationship resolution rely on.
"""

from __future__ import annotations

from app.models.base import Base, TimestampMixin, utcnow
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase

__all__ = [
    "Base",
    "Document",
    "DocumentStatus",
    "KnowledgeBase",
    "TimestampMixin",
    "utcnow",
]
