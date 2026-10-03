"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.schemas.common import LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
async def liveness(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> LivenessResponse:
    """Report that the process is running and able to serve requests."""
    return LivenessResponse(
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ReadinessResponse:
    """Report whether the service is ready to accept traffic.

    No external dependency (object storage, vector index, model provider) is wired
    in at this stage, so the check list is empty. Each adapter added in a later
    phase contributes its own check here, which keeps the probe contract stable.
    """
    return ReadinessResponse(
        status="ok",
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
        checks=[],
    )
