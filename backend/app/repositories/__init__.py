"""Persistence ports and adapters.

Repositories own the translation between domain objects and their storage. Content
storage is expressed as a port here and implemented per backend.
"""

from __future__ import annotations

from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.knowledge_bases import KnowledgeBaseRepository
from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.repositories.storage import DocumentStorage, DocumentStorageError

__all__ = [
    "ChunkRepository",
    "DocumentRepository",
    "DocumentStorage",
    "DocumentStorageError",
    "KnowledgeBaseRepository",
    "LocalFileSystemStorage",
]
