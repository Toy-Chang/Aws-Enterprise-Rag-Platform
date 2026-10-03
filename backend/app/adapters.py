"""Adapter selection: which implementation of each port the configuration asks for.

The composition root calls these builders and hands the results to the services, so the
decision about where documents, vectors and embeddings come from is made in one place and
no service branches on how the platform is deployed.

A builder only receives settings that the configuration has already validated, so the
guards below are unreachable through the environment. They are here to satisfy the type
of the optional setting without silently passing ``None`` into an adapter.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.aws.bedrock_embeddings import BedrockEmbeddingModel
from app.aws.cognito_auth import CognitoTokenVerifier
from app.aws.opensearch_vector_store import OpenSearchVectorStore
from app.aws.s3_storage import S3DocumentStorage
from app.aws.sqs_queue import SqsDocumentQueue
from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.rag.embeddings import EmbeddingModel
from app.rag.hashing_embeddings import HashingEmbeddingModel
from app.rag.in_memory_vector_store import InMemoryVectorStore
from app.rag.vector_store import VectorStore
from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.repositories.queue import DocumentQueue, NullDocumentQueue
from app.repositories.storage import DocumentStorage
from app.security.auth import AnonymousTokenVerifier, TokenVerifier
from app.services.ingestion import IngestionService


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


def build_document_queue(settings: Settings) -> DocumentQueue:
    """Return the queue that ingestion work is published to.

    The default is no queue at all: the ingestion worker polls the database for pending
    documents, so an upload is picked up without anything being published. A deployment
    that publishes to a queue turns the worker off, because two consumers of the same
    pending documents would run the same document twice.
    """
    if settings.queue_backend == "sqs":
        queue_url = settings.sqs_queue_url
        if queue_url is None:  # pragma: no cover - Settings refuses this combination
            raise ValueError("sqs_queue_url is required when queue_backend is 'sqs'")
        return SqsDocumentQueue(queue_url, region=settings.sqs_region)
    return NullDocumentQueue()


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Return the token verifier the configuration asks for.

    The default trusts every request as an unauthenticated, fully privileged principal,
    which is what keeps the local and container stacks usable without an identity
    provider. ``Settings`` refuses that backend in production, so the permissive default
    cannot reach a deployment.
    """
    if settings.auth_backend == "cognito":
        return CognitoTokenVerifier(
            user_pool_id=settings.cognito_user_pool_id,
            client_id=settings.cognito_client_id,
            region=settings.cognito_region,
            issuer=settings.cognito_issuer,
            cache_seconds=settings.cognito_jwks_cache_seconds,
            leeway_seconds=settings.auth_leeway_seconds,
        )
    return AnonymousTokenVerifier()


def build_ingestion_service(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session],
    storage: DocumentStorage,
    embedder: EmbeddingModel,
    vector_store: VectorStore,
    metrics: MetricsRegistry,
) -> IngestionService:
    """Assemble the ingestion service from the adapters it runs against.

    The API process and the queue consumer both call this, so a document is ingested the
    same way whether a worker found it or a message asked for it.
    """
    return IngestionService(
        session_factory=session_factory,
        storage=storage,
        embedder=embedder,
        vector_store=vector_store,
        settings=settings,
        metrics=metrics,
    )
