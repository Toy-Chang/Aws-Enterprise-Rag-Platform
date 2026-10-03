"""HTTP middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.context import new_request_id, reset_request_id, set_request_id
from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlate every request with an identifier and emit one access record.

    The identifier is reused from the inbound request-id header when the caller
    supplies one, and generated otherwise. It is published on ``request.state``
    (so error handlers can report it), bound to the request context (so
    downstream log records inherit it), and echoed back in the response headers.
    """

    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = self._resolve_request_id(request)
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                http_method=request.method,
                http_path=request.url.path,
                duration_ms=_elapsed_ms(started),
                request_id=request_id,
            )
            raise
        finally:
            reset_request_id(token)

        response.headers[self._header_name] = request_id
        logger.info(
            "request_completed",
            http_method=request.method,
            http_path=request.url.path,
            http_status=response.status_code,
            duration_ms=_elapsed_ms(started),
            request_id=request_id,
        )
        return response

    def _resolve_request_id(self, request: Request) -> str:
        inbound = request.headers.get(self._header_name)
        if inbound and inbound.strip():
            return inbound.strip()
        return new_request_id()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
