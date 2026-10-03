"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import EngineDep, SettingsDep
from app.schemas.common import HealthCheck, LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
def liveness(settings: SettingsDep) -> LivenessResponse:
    """Report that the process is running and able to serve requests."""
    return LivenessResponse(
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
def readiness(settings: SettingsDep, engine: EngineDep) -> ReadinessResponse:
    """Report whether the service is ready to accept traffic.

    Every external dependency contributes one check. The document store is not
    probed here yet because its adapter is a local directory in this phase; a check
    becomes meaningful once the AWS implementation replaces it.
    """
    checks = [_check_database(engine)]
    status: Literal["ok", "degraded"] = (
        "ok" if all(check.status == "ok" for check in checks) else "degraded"
    )
    return ReadinessResponse(
        status=status,
        service=settings.name,
        version=settings.version,
        environment=settings.environment,
        checks=checks,
    )


def _check_database(engine: Engine) -> HealthCheck:
    """Confirm the database answers a trivial query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Only the exception type is reported: a driver message can contain the
        # connection string, and a probe response is visible to callers.
        return HealthCheck(name="database", status="degraded", detail=type(exc).__name__)
    return HealthCheck(name="database", status="ok")
