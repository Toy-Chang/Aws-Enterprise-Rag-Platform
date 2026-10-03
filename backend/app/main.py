"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import health, meta
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log process lifecycle events around the server's runtime."""
    settings: Settings = app.state.settings
    logger.info(
        "service_starting",
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
    )
    yield
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
    app.state.settings = resolved

    app.add_middleware(RequestContextMiddleware, header_name=resolved.request_id_header)
    register_exception_handlers(app)

    app.include_router(meta.router)
    app.include_router(health.router)

    return app


app = create_app()
