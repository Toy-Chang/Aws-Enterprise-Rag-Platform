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
from app.repositories.storage import DocumentStorage


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
    yield from session_scope(session_factory)


def get_storage(request: Request) -> DocumentStorage:
    """Return the configured document storage adapter."""
    storage: DocumentStorage = request.app.state.storage
    return storage


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
SessionDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[DocumentStorage, Depends(get_storage)]
