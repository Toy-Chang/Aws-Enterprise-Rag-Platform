"""Context and prompt assembly: how passages become what a generator reads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.passages import Passage

INSTRUCTIONS = """Answer the question using only the numbered context passages below.

Rules:
- Support every statement with the marker of the passage it came from, written as [1].
- If the passages do not answer the question, say that the knowledge base does not
  cover it. Never fall back on knowledge from outside the passages.
- Answer in at most one short paragraph, in the language of the question."""


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """The rendered context, and the passages that fit inside it."""

    text: str
    passages: tuple[Passage, ...]
    skipped: int
    truncated: bool


def build_context(passages: Sequence[Passage], *, max_chars: int) -> ContextBundle:
    """Render passages as numbered, attributed context within a character budget.

    Whole passages are included while they fit, so a citation never points at a
    sentence that was cut in half. The first passage is truncated when it alone
    exceeds the budget, because returning an empty context would throw away a
    retrieval that did find something relevant.

    The returned ``passages`` are the ones actually rendered, in marker order, which is
    what makes a citation list match the context the generator was given.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    blocks: list[str] = []
    included: list[Passage] = []
    skipped = 0
    truncated = False
    used = 0

    for passage in passages:
        block = _render(len(included) + 1, passage)
        if included and used + len(block) > max_chars:
            skipped += 1
            continue
        if not included and len(block) > max_chars:
            block = block[:max_chars]
            truncated = True
        blocks.append(block)
        included.append(passage)
        used += len(block)

    return ContextBundle(
        text="\n\n".join(blocks),
        passages=tuple(included),
        skipped=skipped,
        truncated=truncated,
    )


def build_prompt(question: str, context: str) -> str:
    """Wrap a question and its context in the grounding instructions."""
    return f"{INSTRUCTIONS}\n\nContext passages:\n\n{context}\n\nQuestion: {question}\nAnswer:"


def _render(marker: int, passage: Passage) -> str:
    return f"[{marker}] {passage.label}\n{passage.content.strip()}"
