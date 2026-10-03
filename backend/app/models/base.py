"""Declarative base and shared column mixins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    SQLite does not preserve timezone offsets, so timestamps are stored as naive
    UTC and serialized consistently. The move to PostgreSQL moves these columns to
    ``timestamptz``.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _initial_updated_at(context: Any) -> datetime:
    """Reuse ``created_at`` for a brand new row.

    Letting both columns call :func:`utcnow` independently would leave a fresh row
    with ``updated_at`` a few microseconds after ``created_at``, implying an update
    that never happened.
    """
    created_at = context.get_current_parameters().get("created_at")
    return created_at if isinstance(created_at, datetime) else utcnow()


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


class TimestampMixin:
    """Adds creation and modification timestamps to a model."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_initial_updated_at, onupdate=utcnow, nullable=False
    )
