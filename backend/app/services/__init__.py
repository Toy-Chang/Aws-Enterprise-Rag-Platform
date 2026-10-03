"""Use cases.

Services hold the behaviour of the platform: they enforce domain rules, coordinate
repositories and storage, and raise :mod:`app.core.errors` failures. They never
import the web framework.
"""

from __future__ import annotations

from app.services.documents import DocumentService
from app.services.knowledge_bases import KnowledgeBaseService

__all__ = ["DocumentService", "KnowledgeBaseService"]
