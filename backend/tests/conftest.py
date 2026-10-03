"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Deterministic settings isolated from the developer's environment.

    Each test gets its own SQLite database and document directory under pytest's
    temporary directory, so no state leaks between tests and nothing is written
    into the repository.
    """
    return Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        log_format="json",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=str(tmp_path / "documents"),
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


@pytest.fixture
def storage_dir(settings: Settings) -> Path:
    """The document directory this test's storage adapter writes into."""
    return Path(settings.storage_dir)
