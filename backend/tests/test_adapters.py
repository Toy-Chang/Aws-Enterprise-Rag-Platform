"""Tests for adapter selection."""

from __future__ import annotations

import pytest

from app import adapters
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


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_the_local_defaults_are_selected_and_satisfy_their_ports() -> None:
    settings = _settings()
    storage = adapters.build_storage(settings)
    embedder = adapters.build_embedder(settings)
    store = adapters.build_vector_store(settings)

    assert isinstance(storage, LocalFileSystemStorage)
    assert isinstance(embedder, HashingEmbeddingModel)
    assert isinstance(store, InMemoryVectorStore)
    # The ports are runtime checkable, so this asserts the adapters structurally satisfy
    # the interfaces the services depend on.
    assert isinstance(storage, DocumentStorage)
    assert isinstance(embedder, EmbeddingModel)
    assert isinstance(store, VectorStore)


def test_s3_is_selected_with_its_bucket_prefix_and_region() -> None:
    settings = _settings(
        storage_backend="s3",
        s3_bucket="kb-documents",
        s3_prefix="/tenant-a/",
        s3_region="eu-west-1",
    )
    storage = adapters.build_storage(settings)

    assert isinstance(storage, S3DocumentStorage)
    assert isinstance(storage, DocumentStorage)
    assert storage.bucket == "kb-documents"
    assert storage.prefix == "tenant-a"


def test_bedrock_embeddings_are_selected_with_the_configured_dimensions() -> None:
    settings = _settings(
        embedding_provider="bedrock",
        embedding_dimensions=1024,
        bedrock_embedding_model_id="amazon.titan-embed-text-v2:0",
        bedrock_region="us-west-2",
    )
    embedder = adapters.build_embedder(settings)

    assert isinstance(embedder, BedrockEmbeddingModel)
    assert isinstance(embedder, EmbeddingModel)
    assert embedder.dimensions == 1024
    assert embedder.model_id == "amazon.titan-embed-text-v2:0"


def test_opensearch_is_selected_with_basic_auth() -> None:
    settings = _settings(
        vector_store_backend="opensearch",
        opensearch_endpoint="https://search.example.eu-west-1.es.amazonaws.com",
        opensearch_index="chunks",
        embedding_dimensions=512,
        opensearch_username="platform",
        opensearch_password="secret",
        opensearch_serverless=True,
    )
    store = adapters.build_vector_store(settings)

    assert isinstance(store, OpenSearchVectorStore)
    assert isinstance(store, VectorStore)
    assert store.index == "chunks"
    assert store.dimensions == 512
    assert store.serverless is True


@pytest.mark.parametrize("dimensions", [256, 512, 1024])
def test_the_index_is_sized_by_the_embedding_dimensions(dimensions: int) -> None:
    # One setting drives both, so an index cannot end up sized for a different vector
    # than the embedder produces.
    store = adapters.build_vector_store(_settings(embedding_dimensions=dimensions))

    assert store.dimensions == dimensions


def test_opensearch_without_basic_auth_signs_its_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_credentials() -> None:
        raise RuntimeError("no AWS credentials were found for signing OpenSearch requests")

    monkeypatch.setattr(
        "app.aws.opensearch_vector_store._credentials", _no_credentials, raising=True
    )
    settings = _settings(
        vector_store_backend="opensearch",
        opensearch_endpoint="https://search.example.com",
    )

    # Without a basic-auth pair the client signs with SigV4, which needs credentials.
    with pytest.raises(RuntimeError, match="no AWS credentials"):
        adapters.build_vector_store(settings)
