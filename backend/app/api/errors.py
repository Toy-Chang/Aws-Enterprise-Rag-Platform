"""HTTP rendering of application and framework failures.

Every failure leaves the API as the same envelope, so clients can parse errors
without special-casing each endpoint::

    {"request_id": "...", "error": {"code": "...", "message": "...", "details": {}}}

The error types themselves live in :mod:`app.core.errors`, so services and
repositories raise domain-meaningful failures without importing the web layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from app.core.errors import AppError
from app.core.logging import get_logger
from app.schemas.common import ErrorBody, ErrorResponse

logger = get_logger(__name__)

_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _request_id_header(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "request_id_header", "X-Request-ID")


def _render(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        request_id=_request_id(request),
        error=ErrorBody(code=code, message=message, details=details or {}),
    )
    response_headers = dict(headers or {})
    # Responses produced above the request middleware -- an unexpected exception is
    # rendered by Starlette's outermost error middleware -- still have to carry the
    # correlation header, so the handler sets it here rather than relying on the
    # middleware alone.
    request_id = _request_id(request)
    if request_id is not None:
        response_headers.setdefault(_request_id_header(request), request_id)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
        headers=response_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render a deliberate application error."""
    log = logger.error if exc.status_code >= 500 else logger.warning
    log(
        "application_error",
        error_code=exc.code,
        http_status=exc.status_code,
        detail=str(exc),
    )
    return _render(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render framework-raised HTTP errors (including unmatched routes)."""
    code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return _render(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=dict(exc.headers or {}),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render request validation failures with per-field detail."""
    return _render(
        request,
        status_code=422,
        code="UNPROCESSABLE_ENTITY",
        message="The request payload failed validation.",
        details={"errors": jsonable_encoder(exc.errors())},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Render unexpected failures without leaking internal detail to the caller."""
    logger.error(
        "unhandled_exception",
        error_type=type(exc).__name__,
        request_id=_request_id(request),
        exc_info=exc,
    )
    return _render(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the platform's exception handlers on ``app``."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
