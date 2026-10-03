"""Adapter selection: which implementation of each port the configuration asks for.

The composition root calls these builders and hands the results to the services, so the
decision about where documents, vectors and embeddings come from is made in one place and
no service branches on how the platform is deployed.

A builder only receives settings that the configuration has already validated, so the
guards below are unreachable through the environment. They are here to satisfy the type
of the optional setting without silently passing ``None`` into an adapter.
"""

from __future__ import annotations

from app.aws.bedrock_embeddings import BedrockEmbeddingModel
from app.aws.opensearch_vector_store import OpenSearchVectorStore
from app.aws.s3_storage import S3DocumentStorage
from app.core.config import Settings
from app.rag.embeddings import EmbeddingModel
from app.rag.hashing_embeddings import HashingEmbeddingModel
from app.rag.in_memory_vector_store import InMemoryVectorStore
from app.rag.vector_store import VectorStore
from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.repositories.storage import DocumentStorage


def build_storage(settings: Settings) -> DocumentStorage:
    """Return the document storage the configuration asks for."""
    if settings.storage_backend == "s3":
        bucket = settings.s3_bucket
        if bucket is None:  # pragma: no cover - Settings refuses this combination
            raise ValueError("s3_bucket is required when storage_backend is 's3'")
        return S3DocumentStorage(bucket, prefix=settings.s3_prefix, region=settings.s3_region)
    return LocalFileSystemStorage(settings.storage_dir)


def build_embedder(settings: Settings) -> EmbeddingModel:
    """Return the embedding model the configuration asks for."""
    if settings.embedding_provider == "bedrock":
        return BedrockEmbeddingModel(
            dimensions=settings.embedding_dimensions,
            model_id=settings.bedrock_embedding_model_id,
            region=settings.bedrock_region,
        )
    return HashingEmbeddingModel(settings.embedding_dimensions)


def build_vector_store(settings: Settings) -> VectorStore:
    """Return the vector index the configuration asks for.

    The index is built for ``embedding_dimensions`` because that is the length the
    configured embedder produces. The two are one setting on purpose: an index sized for
    a different vector than the model returns could only fail at query time.
    """
    if settings.vector_store_backend == "opensearch":
        endpoint = settings.opensearch_endpoint
        if endpoint is None:  # pragma: no cover - Settings refuses this combination
            raise ValueError(
                "opensearch_endpoint is required when vector_store_backend is 'opensearch'"
            )
        basic_auth = settings.opensearch_basic_auth
        return OpenSearchVectorStore(
            endpoint=endpoint,
            index=settings.opensearch_index,
            dimensions=settings.embedding_dimensions,
            region=settings.opensearch_region,
            username=basic_auth[0] if basic_auth else None,
            password=basic_auth[1] if basic_auth else None,
            verify_certs=settings.opensearch_verify_certs,
            serverless=settings.opensearch_serverless,
        )
    return InMemoryVectorStore(settings.embedding_dimensions)
