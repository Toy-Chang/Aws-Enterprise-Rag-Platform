"""Retrieval building blocks: embeddings, vector indexes, reranking and generation.

Every capability here is a port with a local adapter, so the platform runs offline
while the AWS adapters -- Bedrock embeddings and generation, OpenSearch or pgvector --
implement the same interfaces.
"""

from __future__ import annotations

from app.rag.bedrock_generation import BedrockAnswerModel
from app.rag.context import ContextBundle, build_context, build_prompt
from app.rag.embeddings import EmbeddingModel
from app.rag.generation import (
    AnswerModel,
    AnswerRequest,
    ExtractiveAnswerModel,
    GeneratedAnswer,
)
from app.rag.hashing_embeddings import HashingEmbeddingModel
from app.rag.in_memory_vector_store import InMemoryVectorStore
from app.rag.passages import Passage
from app.rag.reranking import LexicalOverlapReranker, Reranker
from app.rag.vector_store import VectorMatch, VectorRecord, VectorStore

__all__ = [
    "AnswerModel",
    "AnswerRequest",
    "BedrockAnswerModel",
    "ContextBundle",
    "EmbeddingModel",
    "ExtractiveAnswerModel",
    "GeneratedAnswer",
    "HashingEmbeddingModel",
    "InMemoryVectorStore",
    "LexicalOverlapReranker",
    "Passage",
    "Reranker",
    "VectorMatch",
    "VectorRecord",
    "VectorStore",
    "build_context",
    "build_prompt",
]
