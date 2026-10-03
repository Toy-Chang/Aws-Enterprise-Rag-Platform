"""Tests for the composition root: which adapters a configuration assembles."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.aws.bedrock_embeddings import BedrockEmbeddingModel
from app.aws.cognito_auth import CognitoTokenVerifier
from app.aws.opensearch_vector_store import OpenSearchVectorStore
from app.aws.s3_storage import S3DocumentStorage
from app.aws.sqs_queue import SqsDocumentQueue
from app.core.config import Settings
from app.main import create_app
from app.rag import HashingEmbeddingModel, InMemoryVectorStore
from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.repositories.queue import NullDocumentQueue
from app.security.auth import AnonymousTokenVerifier


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    options: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/rag.db",
        "storage_dir": str(tmp_path / "data"),
        # The worker is started by the lifespan, which these tests do not enter.
        "ingestion_worker_enabled": False,
    }
    options.update(overrides)
    return Settings(_env_file=None, **options)


def test_the_local_stack_is_assembled_from_the_local_adapters(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    assert isinstance(app.state.storage, LocalFileSystemStorage)
    assert isinstance(app.state.embedder, HashingEmbeddingModel)
    assert isinstance(app.state.vector_store, InMemoryVectorStore)


def test_the_aws_stack_is_assembled_from_the_configured_adapters(tmp_path: Path) -> None:
    # Building the clients makes no network call, so this asserts the real wiring: the
    # composition root hands the AWS adapters to the services without any of them
    # knowing which implementation it received.
    app = create_app(
        _settings(
            tmp_path,
            storage_backend="s3",
            s3_bucket="kb-documents",
            embedding_provider="bedrock",
            embedding_dimensions=1024,
            vector_store_backend="opensearch",
            opensearch_endpoint="https://search.example.com",
            opensearch_username="platform",
            opensearch_password="secret",
        )
    )

    assert isinstance(app.state.storage, S3DocumentStorage)
    assert app.state.storage.bucket == "kb-documents"
    assert isinstance(app.state.embedder, BedrockEmbeddingModel)
    assert app.state.embedder.dimensions == 1024
    assert isinstance(app.state.vector_store, OpenSearchVectorStore)
    assert app.state.vector_store.dimensions == 1024
    assert app.state.ingestion is not None
    assert app.state.ingestion_worker is not None


def test_the_index_and_the_embedder_agree_on_the_dimensions(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, embedding_dimensions=512))

    assert app.state.embedder.dimensions == app.state.vector_store.dimensions == 512


def test_a_half_configured_aws_adapter_fails_while_the_process_starts(tmp_path: Path) -> None:
    # The failure has to happen at startup rather than at the first upload, which is the
    # difference between a deployment that reports a bad configuration and one that looks
    # healthy until someone tries to use it.
    with pytest.raises(ValidationError, match="s3_bucket is required"):
        create_app(_settings(tmp_path, storage_backend="s3"))

    with pytest.raises(ValidationError, match="opensearch_endpoint is required"):
        create_app(_settings(tmp_path, vector_store_backend="opensearch"))

    with pytest.raises(ValidationError, match="sqs_queue_url is required"):
        create_app(_settings(tmp_path, queue_backend="sqs"))

    with pytest.raises(ValidationError, match="cognito_user_pool_id is required"):
        create_app(_settings(tmp_path, auth_backend="cognito"))


def test_the_local_stack_has_no_queue(tmp_path: Path) -> None:
    # The worker polls the database, so publishing has to be a harmless no-op rather than
    # an error the upload path would have to know about.
    app = create_app(_settings(tmp_path))

    assert isinstance(app.state.document_queue, NullDocumentQueue)


def test_the_local_stack_trusts_every_request_as_anonymous(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    assert isinstance(app.state.token_verifier, AnonymousTokenVerifier)
    principal = app.state.token_verifier.verify(None)
    assert principal.authenticated is False


def test_cognito_is_selected_with_its_pool(tmp_path: Path) -> None:
    app = create_app(
        _settings(
            tmp_path,
            auth_backend="cognito",
            cognito_user_pool_id="eu-west-1_TESTPOOL",
            cognito_client_id="client-id",
            cognito_region="eu-west-1",
        )
    )

    verifier = app.state.token_verifier
    assert isinstance(verifier, CognitoTokenVerifier)
    assert verifier.issuer == "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_TESTPOOL"


def test_sqs_is_selected_with_its_queue_url(tmp_path: Path) -> None:
    app = create_app(
        _settings(
            tmp_path,
            queue_backend="sqs",
            sqs_queue_url="https://sqs.eu-west-1.amazonaws.com/1/ingestion",
            sqs_region="eu-west-1",
        )
    )

    assert isinstance(app.state.document_queue, SqsDocumentQueue)
    assert app.state.document_queue.queue_url == "https://sqs.eu-west-1.amazonaws.com/1/ingestion"
