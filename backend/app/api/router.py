"""Versioned API router.

Everything mounted here is served under the configured API prefix (``/api/v1`` by
default). Infrastructure endpoints -- probes and service metadata -- stay at the
root so that platform probes never depend on an API version.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import documents, knowledge_bases, query

api_router = APIRouter()
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(query.router)
