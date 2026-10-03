"""Use cases.

Services hold the behaviour of the platform: they enforce domain rules, coordinate
repositories, storage, embedding and indexing, and raise :mod:`app.core.errors`
failures. They never import the web framework.
"""

from __future__ import annotations

from app.services.documents import DocumentService
from app.services.ingestion import IngestionService, rebuild_vector_index
from app.services.knowledge_bases import KnowledgeBaseService

__all__ = [
    "DocumentService",
    "IngestionService",
    "KnowledgeBaseService",
    "rebuild_vector_index",
]
