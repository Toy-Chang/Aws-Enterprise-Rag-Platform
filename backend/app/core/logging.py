"""Structured logging configuration.

Records are rendered either as JSON (ready for CloudWatch Logs ingestion) or as a
human-readable console line. The active request identifier is injected into every
record, including records emitted by third-party libraries.
"""

from __future__ import annotations

import logging
import sys
from typing import IO, Any

import structlog

from app.core.config import Settings
from app.core.context import get_request_id


def _inject_request_id(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Attach the current request identifier to ``event_dict`` when one is bound."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _shared_processors() -> list[Any]:
    """Processors applied to both structlog and standard-library records."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _inject_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


def configure_logging(settings: Settings, *, stream: IO[str] | None = None) -> None:
    """Configure structlog and the root logger.

    ``stream`` exists so tests can capture rendered output without touching the
    global standard streams.
    """
    renderer: Any
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger that renders through the configured formatter."""
    return structlog.get_logger(name)
