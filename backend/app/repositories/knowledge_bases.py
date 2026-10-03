"""Persistence for knowledge base metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeBase


class KnowledgeBaseRepository:
    """Reads and writes knowledge bases through a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, knowledge_base: KnowledgeBase) -> None:
        """Stage a new knowledge base for insertion."""
        self._session.add(knowledge_base)

    def get(self, knowledge_base_id: str) -> KnowledgeBase | None:
        """Return the knowledge base with ``knowledge_base_id``, if it exists."""
        return self._session.get(KnowledgeBase, knowledge_base_id)

    def get_by_name(self, name: str) -> KnowledgeBase | None:
        """Return the knowledge base called ``name``, if one exists."""
        return self._session.scalar(select(KnowledgeBase).where(KnowledgeBase.name == name))

    def list(self) -> list[KnowledgeBase]:
        """Return every knowledge base, newest first."""
        statement = select(KnowledgeBase).order_by(
            KnowledgeBase.created_at.desc(), KnowledgeBase.name
        )
        return list(self._session.scalars(statement))

    def delete(self, knowledge_base: KnowledgeBase) -> None:
        """Stage a knowledge base for removal."""
        self._session.delete(knowledge_base)
