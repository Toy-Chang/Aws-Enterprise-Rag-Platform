"""Module entry point.

Run the API with ``python -m app``. Uvicorn's own logging configuration is
disabled so that every record is rendered by the platform's structured logger,
and its access log is disabled because the request middleware already emits one.
"""

from __future__ import annotations

import uvicorn

from app.core.config import get_settings


def main() -> None:
    """Start the API server using the resolved settings."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
