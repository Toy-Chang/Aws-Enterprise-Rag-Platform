"""Tests for the OpenSearch k-NN vector store adapter."""

from __future__ import annotations

from typing import Any

import pytest

from app.aws.opensearch_vector_store import OpenSearchVectorStore
from app.rag.vector_store import VectorMatch, VectorRecord, VectorStore, VectorStoreError


class StubIndices:
    """A stand-in for the index administration of the client."""

    def __init__(self, owner: StubOpenSearch) -> None:
        self._owner = owner

    def exists(self, **kwargs: Any) -> bool:
        self._owner.calls.append(("exists", kwargs))
        if self._owner.fail == "exists":
            raise RuntimeError("the cluster is unreachable")
        return self._owner.index_exists

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self._owner.calls.append(("create", kwargs))
        if self._owner.created_elsewhere:
            # Another process won the race and made the index first.
            self._owner.index_exists = True
            raise RuntimeError("resource_already_exists_exception")
        if self._owner.fail == "create":
            raise RuntimeError("the cluster is unreachable")
        self._owner.index_exists = True
        return {"acknowledged": True}


class StubOpenSearch:
    """A stand-in for the parts of the OpenSearch client the adapter calls."""

    def __init__(
        self,
        *,
        index_exists: bool = False,
        hits: list[dict[str, Any]] | None = None,
        count: int = 0,
        rejected: int = 0,
        created_elsewhere: bool = False,
        fail: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.index_exists = index_exists
        self.indices = StubIndices(self)
        self._hits = hits if hits is not None else []
        self._count = count
        self._rejected = rejected
        self.created_elsewhere = created_elsewhere
        self.fail = fail

    def bulk(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("bulk", kwargs))
        if self.fail == "bulk":
            raise RuntimeError("the cluster is unreachable")
        items = [{"index": {"status": 201}} for _ in range(0)]
        items += [{"index": {"error": {"type": "mapper_parsing_exception"}}}] * self._rejected
        return {"errors": bool(self._rejected), "items": items}

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("search", kwargs))
        if self.fail == "search":
            raise RuntimeError("the cluster is unreachable")
        return {"hits": {"hits": self._hits}}

    def count(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("count", kwargs))
        if self.fail == "count":
            raise RuntimeError("the cluster is unreachable")
        return {"count": self._count}

    def delete_by_query(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_by_query", kwargs))
        if self.fail == "delete":
            raise RuntimeError("the cluster is unreachable")
        return {"deleted": 1}

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        for call_name, kwargs in reversed(self.calls):
            if call_name == name:
                return kwargs
        raise AssertionError(f"{name} was never called")


def _record(chunk_id: str = "chunk-1", vector: tuple[float, ...] = (0.1, 0.2)) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id,
        document_id="doc-1",
        knowledge_base_id="kb-1",
        vector=vector,
    )


def _hit(chunk_id: str, score: float) -> dict[str, Any]:
    return {
        "_id": chunk_id,
        "_score": score,
        "_source": {
            "chunk_id": chunk_id,
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
        },
    }


def _store(client: StubOpenSearch, **overrides: Any) -> OpenSearchVectorStore:
    options: dict[str, Any] = {"index": "rag-chunks", "dimensions": 2, "client": client}
    options.update(overrides)
    return OpenSearchVectorStore(**options)


def test_the_adapter_satisfies_the_vector_store_port() -> None:
    store = _store(StubOpenSearch())

    assert isinstance(store, VectorStore)
    assert store.dimensions == 2
    assert store.index == "rag-chunks"
    assert store.serverless is False


def test_the_index_is_created_on_the_first_upsert_with_the_mapping() -> None:
    client = StubOpenSearch()
    _store(client).upsert([_record()])

    created = client.last("create")
    assert created["index"] == "rag-chunks"
    vector = created["body"]["mappings"]["properties"]["vector"]
    assert vector["type"] == "knn_vector"
    assert vector["dimension"] == 2
    assert vector["method"] == {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"}
    assert created["body"]["settings"] == {"index": {"knn": True}}


def test_a_serverless_collection_gets_the_engine_it_supports() -> None:
    client = StubOpenSearch()
    _store(client, serverless=True).upsert([_record()])

    method = client.last("create")["body"]["mappings"]["properties"]["vector"]["method"]
    # Serverless collections do not offer nmslib.
    assert method["engine"] == "faiss"


def test_the_index_is_created_once_per_process() -> None:
    client = StubOpenSearch()
    store = _store(client)
    store.upsert([_record("chunk-1")])
    store.upsert([_record("chunk-2")])

    assert client.names().count("create") == 1
    # After the first creation the index is known to exist, so it is not checked again.
    assert client.names().count("exists") == 1


def test_an_index_created_by_another_process_is_not_an_error() -> None:
    client = StubOpenSearch(created_elsewhere=True)

    _store(client).upsert([_record()])
    assert client.names().count("create") == 1


def test_an_index_that_cannot_be_created_is_a_vector_store_error() -> None:
    client = StubOpenSearch(fail="create")

    with pytest.raises(VectorStoreError, match="could not be created"):
        _store(client).upsert([_record()])


def test_upsert_sends_one_index_action_per_record() -> None:
    client = StubOpenSearch()
    _store(client).upsert([_record("chunk-1"), _record("chunk-2")])

    body = client.last("bulk")["body"]
    assert body == [
        {"index": {"_index": "rag-chunks", "_id": "chunk-1"}},
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "vector": [0.1, 0.2],
        },
        {"index": {"_index": "rag-chunks", "_id": "chunk-2"}},
        {
            "chunk_id": "chunk-2",
            "document_id": "doc-1",
            "knowledge_base_id": "kb-1",
            "vector": [0.1, 0.2],
        },
    ]


def test_a_write_waits_for_the_refresh_by_default() -> None:
    client = StubOpenSearch()
    _store(client).upsert([_record()])

    # A document the API reports as ready has to be searchable, and OpenSearch only makes
    # a write visible after a refresh.
    assert client.last("bulk")["refresh"] == "wait_for"


def test_the_refresh_can_be_relaxed_for_a_bulk_rebuild() -> None:
    client = StubOpenSearch()
    _store(client, refresh=False).upsert([_record()])

    assert client.last("bulk")["refresh"] is False


def test_an_empty_upsert_touches_nothing() -> None:
    client = StubOpenSearch()
    _store(client).upsert([])

    assert client.calls == []


def test_a_vector_of_the_wrong_length_is_refused_before_anything_is_sent() -> None:
    client = StubOpenSearch()

    with pytest.raises(ValueError, match=r"chunk 'chunk-1' has 3 dimensions.*configured for 2"):
        _store(client).upsert([_record(vector=(0.1, 0.2, 0.3))])
    assert client.calls == []


def test_a_partially_rejected_bulk_is_a_failure() -> None:
    # A bulk request answers 200 even when actions failed, so reporting success here
    # would make "ready" a lie for a document that is only half indexed.
    client = StubOpenSearch(rejected=1)

    with pytest.raises(VectorStoreError, match="1 of 2 vectors were rejected"):
        _store(client).upsert([_record("chunk-1"), _record("chunk-2")])


def test_a_bulk_that_cannot_be_sent_is_a_vector_store_error() -> None:
    client = StubOpenSearch(fail="bulk", index_exists=True)

    with pytest.raises(VectorStoreError, match="could not be indexed") as caught:
        _store(client).upsert([_record()])
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("reported", "expected"), [(1.0, 1.0), (0.75, 0.5), (0.5, 0.0), (0.0, -1.0)]
)
def test_the_cosinesimil_score_is_converted_back_to_a_cosine(
    reported: float, expected: float
) -> None:
    # Lucene reports cosinesimil as (1 + cos) / 2, while the in-memory adapter and the
    # min_score policy are written against the cosine itself.
    client = StubOpenSearch(index_exists=True, hits=[_hit("chunk-1", reported)])

    matches = _store(client).search([1.0, 0.0], knowledge_base_id="kb-1")

    assert matches[0].score == pytest.approx(expected)


def test_search_returns_matches_from_the_index_order() -> None:
    client = StubOpenSearch(
        index_exists=True,
        hits=[_hit("chunk-2", 0.9), _hit("chunk-1", 0.6)],
    )

    matches = _store(client).search([1.0, 0.0], knowledge_base_id="kb-1")

    assert matches == [
        VectorMatch(
            chunk_id="chunk-2",
            document_id="doc-1",
            knowledge_base_id="kb-1",
            score=pytest.approx(0.8),
        ),
        VectorMatch(
            chunk_id="chunk-1",
            document_id="doc-1",
            knowledge_base_id="kb-1",
            score=pytest.approx(0.2),
        ),
    ]


def test_search_is_scoped_to_one_knowledge_base() -> None:
    client = StubOpenSearch(index_exists=True, hits=[_hit("chunk-1", 1.0)])

    _store(client).search([1.0, 0.0], knowledge_base_id="kb-1", top_k=3)

    knn = client.last("search")["body"]["query"]["knn"]["vector"]
    assert knn["filter"] == {"term": {"knowledge_base_id": "kb-1"}}
    assert knn["k"] == 3
    assert knn["vector"] == [1.0, 0.0]
    assert client.last("search")["body"]["size"] == 3


def test_a_query_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(ValueError, match=r"query has 3 dimensions.*configured for 2"):
        _store(StubOpenSearch()).search([1.0, 0.0, 0.0], knowledge_base_id="kb-1")


@pytest.mark.parametrize("top_k", [0, -1])
def test_a_non_positive_top_k_asks_for_nothing(top_k: int) -> None:
    client = StubOpenSearch(index_exists=True)

    assert _store(client).search([1.0, 0.0], knowledge_base_id="kb-1", top_k=top_k) == []
    assert client.calls == []


def test_searching_an_index_that_does_not_exist_yet_returns_nothing() -> None:
    # An index that has not been created is an empty corpus, not a failure: the platform
    # has to be able to report that it has no evidence before the first document.
    client = StubOpenSearch(index_exists=False)

    assert _store(client).search([1.0, 0.0], knowledge_base_id="kb-1") == []
    assert client.names() == ["exists"]


def test_search_does_not_check_for_the_index_once_it_exists() -> None:
    client = StubOpenSearch(index_exists=True)
    store = _store(client)
    store.upsert([_record()])
    client.calls.clear()

    store.search([1.0, 0.0], knowledge_base_id="kb-1")

    assert client.names() == ["search"]


def test_a_search_that_fails_is_a_vector_store_error() -> None:
    client = StubOpenSearch(index_exists=True, fail="search")

    with pytest.raises(VectorStoreError, match="could not be searched"):
        _store(client).search([1.0, 0.0], knowledge_base_id="kb-1")


def test_a_search_response_with_no_hits_is_empty() -> None:
    client = StubOpenSearch(index_exists=True, hits=[])

    assert _store(client).search([1.0, 0.0], knowledge_base_id="kb-1") == []


def test_count_reads_the_index_size() -> None:
    client = StubOpenSearch(index_exists=True, count=19)

    assert _store(client).count() == 19


def test_count_of_an_index_that_does_not_exist_yet_is_zero() -> None:
    client = StubOpenSearch(index_exists=False)

    assert _store(client).count() == 0
    assert client.names() == ["exists"]


def test_a_count_that_fails_is_a_vector_store_error() -> None:
    with pytest.raises(VectorStoreError, match="could not be counted"):
        _store(StubOpenSearch(index_exists=True, fail="count")).count()


def test_deleting_a_document_removes_its_vectors() -> None:
    client = StubOpenSearch(index_exists=True)

    _store(client).delete_document("doc-1")

    call = client.last("delete_by_query")
    assert call["index"] == "rag-chunks"
    assert call["body"] == {"query": {"term": {"document_id": "doc-1"}}}
    assert call["refresh"] is True


def test_deleting_from_an_index_that_does_not_exist_does_nothing() -> None:
    client = StubOpenSearch(index_exists=False)

    _store(client).delete_document("doc-1")

    assert client.names() == ["exists"]


def test_a_delete_that_fails_is_a_vector_store_error() -> None:
    with pytest.raises(VectorStoreError, match="could not be removed"):
        _store(StubOpenSearch(index_exists=True, fail="delete")).delete_document("doc-1")


def test_an_index_that_cannot_be_inspected_is_a_vector_store_error() -> None:
    with pytest.raises(VectorStoreError, match="could not be inspected"):
        _store(StubOpenSearch(fail="exists")).upsert([_record()])


def test_the_index_name_and_the_dimensions_have_to_be_usable() -> None:
    with pytest.raises(ValueError, match="dimensions must be positive"):
        _store(StubOpenSearch(), dimensions=0)
    with pytest.raises(ValueError, match="index must not be empty"):
        _store(StubOpenSearch(), index="  ")


def test_an_endpoint_is_required_when_no_client_is_injected() -> None:
    with pytest.raises(ValueError, match="endpoint must not be empty"):
        OpenSearchVectorStore(index="rag-chunks", dimensions=2)
