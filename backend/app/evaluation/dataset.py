"""The input of an evaluation: a corpus, questions, and relevance labels.

Labels are written as a document name plus a snippet rather than as chunk identifiers.
Chunk identifiers are generated at ingestion time and change whenever a document is
re-ingested, so a dataset written against them would rot silently; a snippet is resolved
against the ingested chunks when the evaluation runs, and a label that resolves to nothing
is reported as a dataset problem instead of being scored as a miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from app.core.errors import InvalidEvaluationDatasetError
from app.ingestion.parsers import PARSERS


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """One document of the evaluation corpus."""

    name: str
    content: str


@dataclass(frozen=True, slots=True)
class RelevanceLabel:
    """Where a passage that answers the question lives.

    Every chunk of ``document`` whose text contains ``contains`` counts as relevant, so a
    snippet that spans a chunk boundary legitimately resolves to more than one chunk.
    """

    document: str
    contains: str


@dataclass(frozen=True, slots=True)
class EvaluationQuestion:
    """A question, whether it can be answered from the corpus, and what answers it."""

    id: str
    question: str
    answerable: bool
    relevant: tuple[RelevanceLabel, ...]


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    """A corpus with labelled questions.

    A dataset is self-contained: the corpus travels with the questions, so a run does not
    depend on whatever happens to be ingested in the platform, and two runs of the same
    dataset are comparable.
    """

    name: str
    documents: tuple[CorpusDocument, ...]
    questions: tuple[EvaluationQuestion, ...]

    @classmethod
    def create(
        cls,
        *,
        name: str,
        documents: tuple[CorpusDocument, ...] | list[CorpusDocument],
        questions: tuple[EvaluationQuestion, ...] | list[EvaluationQuestion],
    ) -> Self:
        """Build a dataset, rejecting one that could not be scored honestly.

        Everything that can be checked without running the pipeline is checked here, so a
        malformed dataset fails before a temporary knowledge base is created.
        """
        if not name.strip():
            raise InvalidEvaluationDatasetError("A dataset needs a name.")
        if not documents:
            raise InvalidEvaluationDatasetError("A dataset needs at least one document.")
        if not questions:
            raise InvalidEvaluationDatasetError("A dataset needs at least one question.")

        declared = _validate_documents(documents)
        _validate_questions(questions, declared)
        return cls(name=name.strip(), documents=tuple(documents), questions=tuple(questions))


def _validate_documents(documents: tuple[CorpusDocument, ...] | list[CorpusDocument]) -> set[str]:
    names = [document.name for document in documents]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise InvalidEvaluationDatasetError(
            f"Document names must be unique; {', '.join(repr(name) for name in duplicated)} "
            "appear more than once.",
            details={"documents": duplicated},
        )

    for document in documents:
        if not document.name.strip():
            raise InvalidEvaluationDatasetError("Every document needs a name.")
        if not document.content.strip():
            raise InvalidEvaluationDatasetError(
                f"Document {document.name!r} has no content.",
                details={"document": document.name},
            )
        suffix = Path(document.name).suffix.lower()
        if suffix not in PARSERS:
            raise InvalidEvaluationDatasetError(
                f"Document {document.name!r} is in a format the pipeline cannot parse; "
                f"the supported extensions are {', '.join(sorted(PARSERS))}.",
                details={"document": document.name, "supported_extensions": sorted(PARSERS)},
            )

    return set(names)


def _validate_questions(
    questions: tuple[EvaluationQuestion, ...] | list[EvaluationQuestion], declared: set[str]
) -> None:
    ids = [question.id for question in questions]
    duplicated = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicated:
        raise InvalidEvaluationDatasetError(
            f"Question ids must be unique; {', '.join(repr(item) for item in duplicated)} "
            "appear more than once.",
            details={"questions": duplicated},
        )

    for question in questions:
        if not question.id.strip():
            raise InvalidEvaluationDatasetError("Every question needs an id.")
        if not question.question.strip():
            raise InvalidEvaluationDatasetError(
                f"Question {question.id!r} has no text.", details={"question": question.id}
            )

        # The two directions of this are both deliberate. An answerable question with no
        # label would score recall 0 whatever retrieval did, which reads as a retrieval
        # failure rather than as a missing label; an unanswerable question with a label
        # contradicts itself, and the abstention it is supposed to measure would be wrong
        # to expect.
        if question.answerable and not question.relevant:
            raise InvalidEvaluationDatasetError(
                f"Question {question.id!r} is answerable but labels nothing as relevant.",
                details={"question": question.id},
            )
        if not question.answerable and question.relevant:
            raise InvalidEvaluationDatasetError(
                f"Question {question.id!r} is marked unanswerable but labels relevant passages.",
                details={"question": question.id},
            )

        for label in question.relevant:
            if label.document not in declared:
                raise InvalidEvaluationDatasetError(
                    f"Question {question.id!r} labels {label.document!r}, which is not one of "
                    "the dataset's documents.",
                    details={"question": question.id, "document": label.document},
                )
            if not label.contains.strip():
                raise InvalidEvaluationDatasetError(
                    f"Question {question.id!r} has an empty relevance snippet.",
                    details={"question": question.id, "document": label.document},
                )
