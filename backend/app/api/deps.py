"""Shared FastAPI dependencies.

Each dependency reads from ``app.state`` so that tests and alternate deployments
can build an application with their own configuration and resources. The
``*Dep`` aliases are the annotations routes use to declare what they need.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import session_scope
from app.rag import AnswerModel, EmbeddingModel, Reranker, VectorStore
from app.repositories.storage import DocumentStorage
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


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
SessionDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[DocumentStorage, Depends(get_storage)]
VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
IngestionDep = Annotated[IngestionService, Depends(get_ingestion)]
EmbedderDep = Annotated[EmbeddingModel, Depends(get_embedder)]
RerankerDep = Annotated[Reranker | None, Depends(get_reranker)]
AnswerModelDep = Annotated[AnswerModel, Depends(get_answer_model)]
