"""Domain error hierarchy.

These errors carry a stable machine-readable ``code`` and an HTTP ``status_code``
so that the transport layer can translate any deliberate failure into the uniform
response envelope. Services and repositories raise these directly and never import
the web layer.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for failures the platform raises deliberately.

    Subclasses declare a stable machine-readable ``code`` and an HTTP
    ``status_code`` so that domain failures map onto the public API contract.
    """

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    #: Response headers this failure has to carry. A 401 without
    #: ``WWW-Authenticate`` is not a valid challenge, so a subclass can demand one.
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        self.details: dict[str, Any] = dict(details or {})
        declared = headers if headers is not None else (type(self).headers or {})
        self.headers: dict[str, str] = dict(declared)


class BadRequestError(AppError):
    """The caller sent a syntactically valid request that cannot be honoured."""

    status_code = 400
    code = "BAD_REQUEST"
    message = "The request was invalid."


class NotFoundError(AppError):
    """The addressed resource does not exist or is not visible to the caller."""

    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class PayloadTooLargeError(AppError):
    """The request body exceeds the configured size limit."""

    status_code = 413
    code = "PAYLOAD_TOO_LARGE"
    message = "The request payload is too large."


class UnsupportedMediaTypeError(AppError):
    """The document is not one of the supported formats."""

    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    message = "The document format is not supported."


class GenerationFailedError(AppError):
    """The configured answer generator could not produce an answer.

    This is an upstream failure, not a bad request: the caller asked something the
    platform accepted, and the model behind the port did not answer.
    """

    status_code = 502
    code = "GENERATION_FAILED"
    message = "The answer could not be generated."


class InvalidEvaluationDatasetError(AppError):
    """The evaluation dataset could not be scored as written.

    Raised before any work happens, because a dataset that references an undeclared
    document or marks a question answerable without saying what answers it cannot
    produce an honest number. Scoring it as zero would turn a broken label into a
    quality claim.
    """

    status_code = 422
    code = "INVALID_EVALUATION_DATASET"
    message = "The evaluation dataset is not usable."
