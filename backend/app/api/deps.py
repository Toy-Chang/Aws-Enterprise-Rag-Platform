"""Shared FastAPI dependencies.

Each dependency reads from ``app.state`` so that tests and alternate deployments
can build an application with their own configuration and resources. The
``*Dep`` aliases are the annotations routes use to declare what they need.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import session_scope
from app.core.metrics import MetricsRegistry
from app.rag import AnswerModel, EmbeddingModel, Reranker, VectorStore
from app.repositories.queue import DocumentQueue
from app.repositories.storage import DocumentStorage
from app.security.auth import (
    ADMIN,
    EDITOR,
    VIEWER,
    Principal,
    TokenVerifier,
    UnauthenticatedError,
    authorize,
)
from app.services.ingestion import IngestionService


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running application instance."""
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    """Return the database engine bound to the running application instance."""
    engine: Engine = request.app.state.engine
    return engine


def get_db(request: Request) -> Iterator[Session]:
    """Yield a session and close its transaction at the end of the request.

    Committing here rather than inside each service keeps transaction boundaries at
    the edge of the request, so an exception anywhere in a handler rolls the whole
    unit of work back.
    """
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_storage(request: Request) -> DocumentStorage:
    """Return the configured document storage adapter."""
    storage: DocumentStorage = request.app.state.storage
    return storage


def get_vector_store(request: Request) -> VectorStore:
    """Return the configured vector index."""
    vector_store: VectorStore = request.app.state.vector_store
    return vector_store


def get_ingestion(request: Request) -> IngestionService:
    """Return the configured ingestion service."""
    ingestion: IngestionService = request.app.state.ingestion
    return ingestion


def get_document_queue(request: Request) -> DocumentQueue:
    """Return the queue ingestion work is published to.

    The local stack's queue accepts the work and does nothing with it; the ingestion
    worker finds the document by polling the database.
    """
    queue: DocumentQueue = request.app.state.document_queue
    return queue


def get_embedder(request: Request) -> EmbeddingModel:
    """Return the configured embedding model."""
    embedder: EmbeddingModel = request.app.state.embedder
    return embedder


def get_reranker(request: Request) -> Reranker | None:
    """Return the configured reranker, or ``None`` when reranking is disabled."""
    reranker: Reranker | None = request.app.state.reranker
    return reranker


def get_answer_model(request: Request) -> AnswerModel:
    """Return the configured answer generator."""
    answer_model: AnswerModel = request.app.state.answer_model
    return answer_model


def get_metrics(request: Request) -> MetricsRegistry:
    """Return the metrics registry bound to the running application instance."""
    metrics: MetricsRegistry = request.app.state.metrics
    return metrics


def get_token_verifier(request: Request) -> TokenVerifier:
    """Return the configured token verifier."""
    verifier: TokenVerifier = request.app.state.token_verifier
    return verifier


def get_principal(request: Request, verifier: TokenVerifierDep) -> Principal:
    """Return the identity the request's bearer token proves.

    The header is parsed here and the token is verified by the configured verifier, so
    the shape of an HTTP header stays in the web layer and everything about tokens stays
    in the adapter.
    """
    return verifier.verify(_bearer_token(request))


def require_roles(*roles: str) -> Callable[..., Principal]:
    """Return a dependency that admits only the given roles.

    It returns the principal rather than ``None`` so that a route can ask for the
    identity it just authorized if it wants to record who did something.
    """
    required = frozenset(roles)

    def dependency(principal: PrincipalDep) -> Principal:
        authorize(principal, required=required)
        return principal

    return dependency


def _bearer_token(request: Request) -> str | None:
    """Extract the bearer token, or ``None`` when the request carried no credentials.

    A header that is present but malformed is a client error rather than an absent
    credential, so it is refused here instead of being passed on as anonymous.
    """
    header = request.headers.get("authorization")
    if header is None or not header.strip():
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthenticatedError(
            "The Authorization header has to use the Bearer scheme, as in "
            "'Authorization: Bearer <token>'."
        )
    return token.strip()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
SessionDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[DocumentStorage, Depends(get_storage)]
VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
IngestionDep = Annotated[IngestionService, Depends(get_ingestion)]
DocumentQueueDep = Annotated[DocumentQueue, Depends(get_document_queue)]
EmbedderDep = Annotated[EmbeddingModel, Depends(get_embedder)]
RerankerDep = Annotated[Reranker | None, Depends(get_reranker)]
AnswerModelDep = Annotated[AnswerModel, Depends(get_answer_model)]
MetricsDep = Annotated[MetricsRegistry, Depends(get_metrics)]
TokenVerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]

#: The least privilege each kind of endpoint needs. Routers require ``ViewerDep`` as a
#: baseline -- so a newly added route is protected before anyone remembers to protect it
#: -- and state a stricter requirement where the action changes something.
ViewerDep = Annotated[Principal, Depends(require_roles(VIEWER))]
EditorDep = Annotated[Principal, Depends(require_roles(EDITOR))]
AdminDep = Annotated[Principal, Depends(require_roles(ADMIN))]
