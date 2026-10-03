"""Shared response and error schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """The machine-readable part of a failed response."""

    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Human-readable description of the failure.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured context, such as per-field validation errors.",
    )


class ErrorResponse(BaseModel):
    """Envelope returned for every non-successful request."""

    request_id: str | None = Field(
        default=None, description="Correlation identifier for this request."
    )
    error: ErrorBody


class ServiceInfo(BaseModel):
    """Identity of the running service."""

    service: str
    display_name: str
    version: str
    environment: str
    api_version: str


class LivenessResponse(BaseModel):
    """Result of the liveness probe."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str


class HealthCheck(BaseModel):
    """Outcome of a single readiness dependency check."""

    name: str
    status: Literal["ok", "degraded"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Result of the readiness probe."""

    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    checks: list[HealthCheck] = Field(default_factory=list)
