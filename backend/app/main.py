"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router
from app.api.routes import health, meta
from app.core.config import Settings, get_settings
from app.core.db import create_db_engine, create_session_factory, init_db
from app.core.logging import configure_logging, get_logger
from app.rag import HashingEmbeddingModel, InMemoryVectorStore
from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.services.ingestion import IngestionService, rebuild_vector_index
from app.services.worker import IngestionWorker

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare and release process-wide resources around the server's runtime."""
    settings: Settings = app.state.settings
    logger.info(
        "service_starting",
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
    )
    init_db(app.state.engine)
    logger.info("database_ready", dialect=app.state.engine.dialect.name)

    # Documents caught mid-ingestion by a restart are queued again, and the index is
    # rebuilt from the stored embeddings, so what is searchable matches what the API
    # reports as ready.
    requeued = app.state.ingestion.recover_interrupted()
    if requeued:
        logger.info("interrupted_ingestions_requeued", documents=requeued)

    indexed = rebuild_vector_index(app.state.session_factory, app.state.vector_store)
    logger.info(
        "vector_index_ready",
        backend=type(app.state.vector_store).__name__,
        dimensions=app.state.vector_store.dimensions,
        vectors=indexed,
    )

    if settings.ingestion_worker_enabled:
        app.state.ingestion_worker.start()

    yield

    app.state.ingestion_worker.stop()
    app.state.engine.dispose()
    logger.info("service_stopped", service=settings.name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Passing ``settings`` keeps tests and alternate deployments from depending on
    the process-wide environment.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    app = FastAPI(
        title=resolved.display_name,
        version=resolved.version,
        summary="Cloud-native enterprise knowledge retrieval and RAG platform.",
        lifespan=lifespan,
    )

    # Resources live on app.state, so a dependency hands them to a request without
    # any module-level singletons. The retrieval and storage adapters are the local
    # ones; the AWS implementations are swapped in here and nowhere else.
    app.state.settings = resolved
    app.state.engine = create_db_engine(resolved)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.storage = LocalFileSystemStorage(resolved.storage_dir)
    app.state.embedder = HashingEmbeddingModel(resolved.embedding_dimensions)
    app.state.vector_store = InMemoryVectorStore(resolved.embedding_dimensions)
    app.state.ingestion = IngestionService(
        session_factory=app.state.session_factory,
        storage=app.state.storage,
        embedder=app.state.embedder,
        vector_store=app.state.vector_store,
        settings=resolved,
    )
    app.state.ingestion_worker = IngestionWorker(
        app.state.ingestion, poll_seconds=resolved.ingestion_poll_seconds
    )

    app.add_middleware(RequestContextMiddleware, header_name=resolved.request_id_header)
    register_exception_handlers(app)

    app.include_router(meta.router)
    app.include_router(health.router)
    app.include_router(api_router, prefix=resolved.api_v1_prefix)

    return app


app = create_app()
