"""Versioned API router.

Everything mounted here is served under the configured API prefix (``/api/v1`` by
default). Infrastructure endpoints -- probes and service metadata -- stay at the
root so that platform probes never depend on an API version.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.api.routes import documents, evaluations, knowledge_bases, metrics, query
from app.security.auth import VIEWER

# The baseline is the least privilege that can read anything: every route under the
# versioned prefix needs an authenticated caller holding at least the viewer role, and a
# route that changes something states a stricter requirement of its own. Putting the
# baseline here rather than on each route is what makes a newly added router protected by
# default instead of protected once someone remembers.
api_router = APIRouter(dependencies=[Depends(require_roles(VIEWER))])
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(query.router)
api_router.include_router(evaluations.router)
api_router.include_router(metrics.router)
