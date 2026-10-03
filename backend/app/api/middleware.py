"""HTTP middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.context import new_request_id, reset_request_id, set_request_id
from app.core.logging import get_logger
from app.core.metrics import MetricsRegistry
from app.core.timing import elapsed_ms

logger = get_logger(__name__)

UNMATCHED_ROUTE = "http.route.unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlate every request with an identifier and emit one access record.

    The identifier is reused from the inbound request-id header when the caller
    supplies one, and generated otherwise. It is published on ``request.state``
    (so error handlers can report it), bound to the request context (so
    downstream log records inherit it), and echoed back in the response headers.

    The same pass records the request in the metrics registry, so the counters and
    the access log cannot disagree about how many requests arrived.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Request-ID",
        metrics: MetricsRegistry,
    ) -> None:
        super().__init__(app)
        self._header_name = header_name
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = self._resolve_request_id(request)
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        self._metrics.increment("http.requests.total")
        try:
            response = await call_next(request)
        except Exception:
            # The failure never reaches a response object, but it is still a request
            # that took time and produced a 5xx, so it is recorded before it propagates.
            self._record(request, started, status_code=500)
            logger.exception(
                "request_failed",
                http_method=request.method,
                http_path=request.url.path,
                duration_ms=elapsed_ms(started),
                request_id=request_id,
            )
            raise
        finally:
            reset_request_id(token)

        response.headers[self._header_name] = request_id
        self._record(request, started, status_code=response.status_code)
        logger.info(
            "request_completed",
            http_method=request.method,
            http_path=request.url.path,
            http_status=response.status_code,
            duration_ms=elapsed_ms(started),
            request_id=request_id,
        )
        return response

    def _record(self, request: Request, started: float, *, status_code: int) -> None:
        """Record one finished request against its route template.

        The label is the template as the router declares it -- ``/knowledge-bases/{id}``
        rather than ``/knowledge-bases/8f3c…`` -- because a concrete path would let a
        caller invent unbounded metric series simply by inventing identifiers. The API
        version prefix is deliberately not part of the label, so changing
        ``APP_API_V1_PREFIX`` does not split every counter, and anything that matched no
        route shares one bucket. The template is available because routing writes it to
        the scope that the middleware and the route share.

        Recording happens after the response is produced, so the request that reads the
        metrics endpoint is visible in its own snapshot as a request but not yet as a
        response. That is inherent to reading metrics from inside the request being
        measured, and it is asserted rather than left as a surprise.
        """
        self._metrics.observe("http.request", elapsed_ms(started))
        self._metrics.increment(f"http.responses.{status_code // 100}xx")

        template = getattr(request.scope.get("route"), "path", None)
        self._metrics.increment(UNMATCHED_ROUTE if not template else f"http.route.{template}")

    def _resolve_request_id(self, request: Request) -> str:
        inbound = request.headers.get(self._header_name)
        if inbound and inbound.strip():
            return inbound.strip()
        return new_request_id()
