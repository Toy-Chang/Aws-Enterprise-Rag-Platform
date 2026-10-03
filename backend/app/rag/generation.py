"""Port for answer generation, and the local extractive adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.rag.passages import Passage


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    """Everything a generator is given.

    ``context`` is the numbered, attributed text built from ``passages``, and is what a
    generative model reads. ``passages`` is passed alongside it for adapters that
    extract rather than generate, and is the reason a citation can be resolved without
    parsing the model's output.
    """

    question: str
    context: str
    passages: tuple[Passage, ...]


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """What a generator returned, with token usage when it reports any."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class AnswerModel(Protocol):
    """Turns a question and retrieved context into an answer."""

    name: str
    kind: str

    def answer(self, request: AnswerRequest) -> GeneratedAnswer:
        """Answer ``request.question`` from ``request.context``."""
        ...


class ExtractiveAnswerModel:
    """Returns the retrieved passages verbatim, under their citation markers.

    This is not a language model. It composes no sentences, so it cannot invent
    content, and it exists so the whole query pipeline — retrieval, thresholding,
    context construction, citations and tracing — runs and is tested offline. ``kind``
    reports the difference to callers, and a Bedrock model replaces it in the AWS
    deployment.
    """

    name = "extractive-local"
    kind = "extractive"

    def answer(self, request: AnswerRequest) -> GeneratedAnswer:
        if not request.passages:
            raise ValueError("an answer needs at least one passage")

        text = "\n\n".join(
            f"[{marker}] {passage.content.strip()}"
            for marker, passage in enumerate(request.passages, start=1)
        )
        return GeneratedAnswer(text=text)
