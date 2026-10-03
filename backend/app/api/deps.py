"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running application instance.

    Reading from ``app.state`` rather than the cached process singleton keeps
    tests and multi-app deployments able to inject their own configuration.
    """
    settings: Settings = request.app.state.settings
    return settings
