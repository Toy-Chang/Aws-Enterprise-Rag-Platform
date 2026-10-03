"""OpenSearch k-NN implementation of the vector store port."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.core.logging import get_logger
from app.rag.vector_store import VectorMatch, VectorRecord, VectorStoreError

logger = get_logger(__name__)

#: Seconds the client waits for a response. A search that takes longer than this fails
#: as a vector store error instead of holding the request open.
_TIMEOUT_SECONDS = 10


class OpenSearchIndicesClient(Protocol):
    """The index administration this adapter performs."""

    def exists(self, **kwargs: Any) -> Any:
        """Whether an index exists."""
        ...

    def create(self, **kwargs: Any) -> dict[str, Any]:
        """Create an index."""
        ...


class OpenSearchClient(Protocol):
    """The OpenSearch operations this adapter performs."""

    indices: OpenSearchIndicesClient

    def bulk(self, **kwargs: Any) -> dict[str, Any]:
        """Index a batch of documents."""
        ...

    def search(self, **kwargs: Any) -> dict[str, Any]:
        """Run a search."""
        ...

    def count(self, **kwargs: Any) -> dict[str, Any]:
        """Count documents in an index."""
        ...

    def delete_by_query(self, **kwargs: Any) -> dict[str, Any]:
        """Delete every document matching a query."""
        ...


class OpenSearchVectorStore:
    """Indexes chunk vectors in an OpenSearch k-NN index.

    Two decisions are worth stating plainly.

    **The score is converted.** OpenSearch reports a ``cosinesimil`` score as
    ``(1 + cos) / 2``, while the in-memory adapter returns the cosine itself, and
    ``retrieval_min_score`` is a policy written against that scale. The conversion
    happens here, in the adapter, so that a threshold means the same thing whichever
    index answered. Changing the space type would silently change what "relevant
    enough" means, which is why it is not a setting.

    **An upsert waits for the refresh.** OpenSearch makes a document searchable after a
    refresh, not when the write returns. A document the API reports as ``ready`` has to
    actually be there, so writes refresh with ``wait_for`` by default. That costs
    latency per batch, and it is the honest price of "ready means searchable".

    The client is injected so that the query and mapping can be tested without a
    cluster, and so that ``opensearchpy`` is imported only when the adapter has to build
    its own client.
    """

    def __init__(
        self,
        *,
        index: str,
        dimensions: int,
        endpoint: str = "",
        region: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certs: bool = True,
        serverless: bool = False,
        refresh: str | bool = "wait_for",
        client: OpenSearchClient | None = None,
    ) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        if not index.strip():
            raise ValueError("index must not be empty")
        self._index = index
        self._dimensions = dimensions
        self._serverless = serverless
        self._refresh = refresh
        # Ingestion runs on a worker thread while requests search, so index creation is
        # guarded: two threads must not both decide the index is missing.
        self._lock = threading.Lock()
        self._index_ready = False

        if client is not None:
            self._client = client
        else:
            if not endpoint.strip():
                raise ValueError("endpoint must not be empty")
            if not verify_certs:
                logger.warning("opensearch_tls_verification_disabled", endpoint=endpoint)
            self._client = _create_client(
                endpoint=endpoint,
                region=region,
                username=username,
                password=password,
                verify_certs=verify_certs,
                serverless=serverless,
            )

    @property
    def dimensions(self) -> int:
        """Length of every vector the index accepts."""
        return self._dimensions

    @property
    def index(self) -> str:
        """The index name."""
        return self._index

    @property
    def serverless(self) -> bool:
        """Whether the index is on OpenSearch Serverless."""
        return self._serverless

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        batch = list(records)
        if not batch:
            return
        self._validate_dimensions((record.chunk_id, len(record.vector)) for record in batch)
        self._ensure_index()

        actions: list[dict[str, Any]] = []
        for record in batch:
            actions.append({"index": {"_index": self._index, "_id": record.chunk_id}})
            actions.append(
                {
                    "chunk_id": record.chunk_id,
                    "document_id": record.document_id,
                    "knowledge_base_id": record.knowledge_base_id,
                    "vector": list(record.vector),
                }
            )
        try:
            response = self._client.bulk(body=actions, refresh=self._refresh)
        except Exception as exc:
            raise VectorStoreError("the vectors could not be indexed") from exc

        # A bulk request answers 200 even when some actions failed, so the per-item
        # result is what decides whether this call succeeded. Reporting success while
        # half a document is missing from the index would make "ready" a lie.
        rejected = _rejected_count(response)
        if rejected:
            raise VectorStoreError(f"{rejected} of {len(batch)} vectors were rejected by the index")

    def delete_document(self, document_id: str) -> None:
        if not self._index_ready and not self._index_exists():
            return
        try:
            self._client.delete_by_query(
                index=self._index,
                body={"query": {"term": {"document_id": document_id}}},
                refresh=True,
                conflicts="proceed",
            )
        except Exception as exc:
            raise VectorStoreError(
                f"the vectors of document {document_id!r} could not be removed"
            ) from exc

    def search(
        self, vector: Sequence[float], *, knowledge_base_id: str, top_k: int = 5
    ) -> list[VectorMatch]:
        if len(vector) != self._dimensions:
            raise ValueError(
                f"query has {len(vector)} dimensions, but the index is configured for "
                f"{self._dimensions}"
            )
        if top_k < 1:
            return []
        if not self._index_ready and not self._index_exists():
            # An index that does not exist yet is an empty corpus, not a failure: the
            # platform has to be able to report that it has no evidence before the first
            # document has been ingested.
            return []

        body = {
            "size": top_k,
            "query": {
                "knn": {
                    "vector": {
                        "vector": list(vector),
                        "k": top_k,
                        "filter": {"term": {"knowledge_base_id": knowledge_base_id}},
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "knowledge_base_id"],
        }
        try:
            response = self._client.search(index=self._index, body=body)
        except Exception as exc:
            raise VectorStoreError("the index could not be searched") from exc
        return [_match(hit) for hit in _hits(response)]

    def count(self) -> int:
        if not self._index_ready and not self._index_exists():
            return 0
        try:
            response = self._client.count(index=self._index)
        except Exception as exc:
            raise VectorStoreError("the index could not be counted") from exc
        return int(response.get("count", 0))

    def _validate_dimensions(self, sizes: Iterable[tuple[str, int]]) -> None:
        """Refuse a vector the index could not store, before sending anything."""
        for chunk_id, size in sizes:
            if size != self._dimensions:
                raise ValueError(
                    f"chunk {chunk_id!r} has {size} dimensions, but the index is "
                    f"configured for {self._dimensions}"
                )

    def _ensure_index(self) -> None:
        """Create the index if it is missing, once per process."""
        if self._index_ready:
            return
        with self._lock:
            if self._index_ready:
                return
            if not self._index_exists():
                try:
                    self._client.indices.create(index=self._index, body=self._mapping())
                    logger.info(
                        "opensearch_index_created",
                        index=self._index,
                        dimensions=self._dimensions,
                        serverless=self._serverless,
                    )
                except Exception as exc:
                    # Another process may have created the index between the check and
                    # the create. That is not a failure worth reporting.
                    if not self._index_exists():
                        raise VectorStoreError(
                            f"the index {self._index!r} could not be created"
                        ) from exc
            self._index_ready = True

    def _index_exists(self) -> bool:
        try:
            return bool(self._client.indices.exists(index=self._index))
        except Exception as exc:
            raise VectorStoreError("the index could not be inspected") from exc

    def _mapping(self) -> dict[str, Any]:
        """The index definition, including the vector field and its distance."""
        return {
            "settings": {"index": {"knn": True}},
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "knowledge_base_id": {"type": "keyword"},
                    "vector": {
                        "type": "knn_vector",
                        "dimension": self._dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            # Serverless collections do not offer the nmslib engine.
                            "engine": "faiss" if self._serverless else "nmslib",
                        },
                    },
                }
            },
        }


def _to_cosine(score: Any) -> float:
    """Convert an OpenSearch ``cosinesimil`` score back to a cosine similarity."""
    return 2.0 * float(score) - 1.0


def _match(hit: dict[str, Any]) -> VectorMatch:
    """Turn one search hit into a match on the scale the rest of the platform uses."""
    source = hit.get("_source")
    fields = source if isinstance(source, dict) else {}
    return VectorMatch(
        chunk_id=str(fields.get("chunk_id", hit.get("_id", ""))),
        document_id=str(fields.get("document_id", "")),
        knowledge_base_id=str(fields.get("knowledge_base_id", "")),
        score=_to_cosine(hit.get("_score", 0.0)),
    )


def _hits(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the hits of a search response, tolerating a shape that has none."""
    hits = response.get("hits")
    if not isinstance(hits, dict):
        return []
    found = hits.get("hits")
    if not isinstance(found, list):
        return []
    return [hit for hit in found if isinstance(hit, dict)]


def _rejected_count(response: dict[str, Any]) -> int:
    """Count the bulk actions the index refused."""
    items = response.get("items")
    if not isinstance(items, list):
        return 0
    rejected = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if any(isinstance(outcome, dict) and outcome.get("error") for outcome in item.values()):
            rejected += 1
    return rejected


def _hosts(endpoint: str) -> list[dict[str, Any]]:
    """Turn an endpoint URL into the host list the client expects."""
    parsed = urlsplit(endpoint if "//" in endpoint else f"//{endpoint}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"could not read a host out of the endpoint {endpoint!r}")
    port = parsed.port or (443 if parsed.scheme != "http" else 9200)
    return [{"host": host, "port": port}]


def _create_client(
    *,
    endpoint: str,
    region: str | None,
    username: str | None,
    password: str | None,
    verify_certs: bool,
    serverless: bool,
) -> OpenSearchClient:
    """Build an OpenSearch client, signing with SigV4 unless basic auth is configured."""
    try:
        from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "the OpenSearch vector store needs its client: install the 'aws' extra "
            "(pip install -e '.[aws]') or set APP_VECTOR_STORE_BACKEND=memory"
        ) from exc

    if username and password:
        http_auth: Any = (username, password)
    else:
        # A managed domain and a serverless collection are signed with different
        # service names, and getting it wrong is an authentication failure.
        http_auth = AWSV4SignerAuth(
            _credentials(), region or "us-east-1", "aoss" if serverless else "es"
        )

    client: OpenSearchClient = OpenSearch(
        hosts=_hosts(endpoint),
        http_auth=http_auth,
        use_ssl=urlsplit(endpoint if "//" in endpoint else f"//{endpoint}").scheme != "http",
        verify_certs=verify_certs,
        connection_class=RequestsHttpConnection,
        timeout=_TIMEOUT_SECONDS,
    )
    return client


def _credentials() -> Any:
    """Return credentials the request signer can use, or explain what is missing."""
    try:
        from botocore.session import Session
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "signing OpenSearch requests needs the AWS SDK: install the 'aws' extra "
            "(pip install -e '.[aws]')"
        ) from exc

    credentials = Session().get_credentials()
    if credentials is None:
        raise RuntimeError(
            "no AWS credentials were found for signing OpenSearch requests: set "
            "APP_OPENSEARCH_USERNAME and APP_OPENSEARCH_PASSWORD, or configure "
            "credentials the AWS SDK can find"
        )
    return credentials
