"""Tests for the in-memory vector index."""

from __future__ import annotations

import pytest

from app.rag import InMemoryVectorStore, VectorRecord

DIMENSIONS = 3


def _record(
    chunk_id: str,
    *,
    document_id: str = "doc-1",
    knowledge_base_id: str = "kb-1",
    vector: tuple[float, ...] = (1.0, 0.0, 0.0),
) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        knowledge_base_id=knowledge_base_id,
        vector=vector,
    )


def test_search_ranks_the_closest_vector_first() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert(
        [
            _record("exact", vector=(1.0, 0.0, 0.0)),
            _record("orthogonal", vector=(0.0, 1.0, 0.0)),
            _record("opposite", vector=(-1.0, 0.0, 0.0)),
        ]
    )

    matches = store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=3)

    assert [match.chunk_id for match in matches] == ["exact", "orthogonal", "opposite"]
    assert matches[0].score == pytest.approx(1.0)
    assert matches[2].score == pytest.approx(-1.0)


def test_search_is_scoped_to_one_knowledge_base() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert(
        [
            _record("here", knowledge_base_id="kb-1"),
            _record("elsewhere", knowledge_base_id="kb-2"),
        ]
    )

    matches = store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=10)

    assert [match.chunk_id for match in matches] == ["here"]
    assert matches[0].knowledge_base_id == "kb-1"


def test_top_k_limits_the_number_of_matches() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert([_record(f"chunk-{index}") for index in range(5)])

    assert len(store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=2)) == 2
    assert store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=0) == []


def test_upsert_replaces_a_record_with_the_same_chunk_id() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert([_record("chunk-1", vector=(1.0, 0.0, 0.0))])
    store.upsert([_record("chunk-1", vector=(0.0, 1.0, 0.0))])

    matches = store.search((0.0, 1.0, 0.0), knowledge_base_id="kb-1", top_k=5)

    assert store.count() == 1
    assert matches[0].score == pytest.approx(1.0)


def test_delete_document_removes_only_that_document() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert(
        [
            _record("a", document_id="doc-1"),
            _record("b", document_id="doc-1"),
            _record("c", document_id="doc-2"),
        ]
    )

    store.delete_document("doc-1")

    matches = store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=10)
    assert [match.chunk_id for match in matches] == ["c"]
    assert store.count() == 1


def test_deleting_an_unknown_document_is_not_an_error() -> None:
    store = InMemoryVectorStore(DIMENSIONS)

    store.delete_document("never-indexed")

    assert store.count() == 0


def test_equal_scores_come_back_in_a_stable_order() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert([_record("zebra"), _record("alpha"), _record("middle")])

    matches = store.search((1.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=3)

    assert [match.chunk_id for match in matches] == ["alpha", "middle", "zebra"]


def test_a_zero_vector_is_similar_to_nothing() -> None:
    store = InMemoryVectorStore(DIMENSIONS)
    store.upsert([_record("chunk-1")])

    matches = store.search((0.0, 0.0, 0.0), knowledge_base_id="kb-1", top_k=1)

    assert matches[0].score == 0.0


def test_a_vector_of_the_wrong_width_is_rejected_on_upsert() -> None:
    store = InMemoryVectorStore(DIMENSIONS)

    with pytest.raises(ValueError, match="dimensions"):
        store.upsert([_record("chunk-1", vector=(1.0, 0.0))])


def test_a_query_of_the_wrong_width_is_rejected() -> None:
    store = InMemoryVectorStore(DIMENSIONS)

    with pytest.raises(ValueError, match="dimensions"):
        store.search((1.0, 0.0), knowledge_base_id="kb-1")


def test_a_non_positive_dimension_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        InMemoryVectorStore(0)
