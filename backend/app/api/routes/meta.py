"""Service metadata endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.schemas.common import ServiceInfo

router = APIRouter(tags=["meta"])


@router.get("/", response_model=ServiceInfo, summary="Service metadata")
async def service_info(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ServiceInfo:
    """Return the service identity and the API version exposed under ``/api``."""
    return ServiceInfo(
        service=settings.name,
        display_name=settings.display_name,
        version=settings.version,
        environment=settings.environment,
        api_version=settings.api_version,
    )
