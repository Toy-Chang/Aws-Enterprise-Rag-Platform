"""Database engine, session factory and schema bootstrap."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import Base


def create_db_engine(settings: Settings) -> Engine:
    """Build the SQLAlchemy engine for the configured database URL."""
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")
    connect_args: dict[str, object] = {}
    if is_sqlite:
        # Synchronous endpoints run in a worker thread, so a connection created on
        # one thread may be used on another.
        connect_args["check_same_thread"] = False

    engine = create_engine(url, connect_args=connect_args, future=True)
    if is_sqlite:
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    """Apply the per-connection settings SQLite needs to behave predictably."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        # Foreign keys are off by default in SQLite.
        cursor.execute("PRAGMA foreign_keys=ON")
        # The default rollback journal blocks readers while a write is in flight. WAL
        # lets the ingestion worker read while a request writes, which matters because
        # both run in this process. SQLite still allows only one writer at a time.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db(engine: Engine) -> None:
    """Create the schema for the current models.

    This is enough while the schema is young and local. Alembic migrations replace
    it as soon as the service is deployed anywhere holding data worth preserving.
    """
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Open a session, committing on success and rolling back on failure.

    Used both by the request dependency and by background work, so that a unit of
    work has the same boundaries wherever it runs.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
