"""Retrieval building blocks: embedding models and vector indexes.

Both are ports with a local adapter, so the platform runs offline while the AWS
adapters -- Bedrock embeddings and OpenSearch or pgvector -- implement the same
interfaces.
"""

from __future__ import annotations

from app.rag.embeddings import EmbeddingModel
from app.rag.hashing_embeddings import HashingEmbeddingModel
from app.rag.in_memory_vector_store import InMemoryVectorStore
from app.rag.vector_store import VectorMatch, VectorRecord, VectorStore

__all__ = [
    "EmbeddingModel",
    "HashingEmbeddingModel",
    "InMemoryVectorStore",
    "VectorMatch",
    "VectorRecord",
    "VectorStore",
]
