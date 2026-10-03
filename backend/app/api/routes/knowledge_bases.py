"""Knowledge base endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep, StorageDep
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseRead
from app.services.knowledge_bases import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge base",
)
def create_knowledge_base(
    payload: KnowledgeBaseCreate, session: SessionDep, storage: StorageDep
) -> KnowledgeBaseRead:
    """Create a knowledge base. Names are unique across the platform."""
    knowledge_base = KnowledgeBaseService(session, storage).create(payload)
    return KnowledgeBaseRead.model_validate(knowledge_base)


@router.get("", summary="List knowledge bases")
def list_knowledge_bases(session: SessionDep, storage: StorageDep) -> list[KnowledgeBaseRead]:
    """Return every knowledge base, newest first."""
    knowledge_bases = KnowledgeBaseService(session, storage).list()
    return [KnowledgeBaseRead.model_validate(item) for item in knowledge_bases]


@router.get("/{knowledge_base_id}", summary="Get a knowledge base")
def get_knowledge_base(
    knowledge_base_id: str, session: SessionDep, storage: StorageDep
) -> KnowledgeBaseRead:
    """Return one knowledge base."""
    knowledge_base = KnowledgeBaseService(session, storage).get(knowledge_base_id)
    return KnowledgeBaseRead.model_validate(knowledge_base)


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge base",
)
def delete_knowledge_base(
    knowledge_base_id: str, session: SessionDep, storage: StorageDep
) -> Response:
    """Delete a knowledge base and every document it holds."""
    KnowledgeBaseService(session, storage).delete(knowledge_base_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
