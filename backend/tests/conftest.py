"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings isolated from the developer's environment."""
    return Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        log_format="json",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A freshly built application instance bound to the test settings."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An HTTP client whose context manager runs the application lifespan."""
    with TestClient(app) as test_client:
        yield test_client
