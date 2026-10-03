"""Amazon Bedrock embedding model behind the :class:`EmbeddingModel` port."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any, Protocol

from app.rag.embeddings import EmbeddingFailedError


class BedrockRuntimeClient(Protocol):
    """The one Bedrock Runtime operation this adapter performs."""

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        """Invoke a model with a JSON body and return its response."""
        ...


class BedrockEmbeddingModel:
    """Embeds text with an Amazon Bedrock embedding model.

    The request shape is Titan Text Embeddings: one text in, one vector out. That shape
    is why :meth:`embed_documents` loops rather than batching. A model with a batch
    operation would embed a document in one call; this one needs a call per chunk, so
    ingesting a document with nineteen chunks is nineteen requests. It is a real cost of
    ingestion, and it is the reason the local run uses the hashing model instead.

    The configured dimension count is sent with every request and the response is
    checked against it. A vector of the wrong length would otherwise be stored happily
    and only fail later, at search time, as a dimension mismatch inside the index --
    which is a much worse place to discover a configuration mistake than at the call
    that produced it. Non-finite values are rejected for the same reason: a single NaN
    would make every cosine similarity it takes part in a NaN, and the ranking would
    silently become meaningless.
    """

    def __init__(
        self,
        *,
        dimensions: int,
        model_id: str = "amazon.titan-embed-text-v2:0",
        region: str | None = None,
        normalize: bool = True,
        client: BedrockRuntimeClient | None = None,
    ) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions
        self._model_id = model_id
        self._normalize = normalize
        self._client = client if client is not None else _create_client(region)

    @property
    def dimensions(self) -> int:
        """Length of every vector this model produces."""
        return self._dimensions

    @property
    def model_id(self) -> str:
        """The model identifier, reported in the startup log."""
        return self._model_id

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of chunk texts, one request per text."""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingFailedError("the text to embed was empty")

        body = json.dumps(
            {
                "inputText": text,
                "dimensions": self._dimensions,
                "normalize": self._normalize,
            }
        )
        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                body=body,
                accept="application/json",
                contentType="application/json",
            )
        except Exception as exc:
            # Credentials, throttling, an unknown model id and a network failure are all
            # the same thing to a caller: the text could not be embedded.
            raise EmbeddingFailedError(
                f"the model {self._model_id!r} could not be reached"
            ) from exc

        return self._parse(response)

    def _parse(self, response: dict[str, Any]) -> list[float]:
        """Pull the vector out of an InvokeModel response, or fail loudly."""
        try:
            payload = json.loads(_body_bytes(response.get("body")))
            values = [float(value) for value in payload["embedding"]]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingFailedError("the model returned no usable embedding") from exc

        if len(values) != self._dimensions:
            raise EmbeddingFailedError(
                f"the model returned {len(values)} dimensions, but the index is "
                f"configured for {self._dimensions}"
            )
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingFailedError("the model returned a non-finite value")
        return values


def _body_bytes(body: Any) -> bytes:
    """Return an InvokeModel response body as bytes."""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")

    read = getattr(body, "read", None)
    if read is None:
        raise EmbeddingFailedError("the model response carried no body")
    return bytes(read())


def _create_client(region: str | None) -> BedrockRuntimeClient:
    """Build a Bedrock Runtime client, or explain what is missing."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "the Bedrock embedding model needs the AWS SDK: install the 'aws' extra "
            "(pip install -e '.[aws]') or set APP_EMBEDDING_PROVIDER=local"
        ) from exc

    client: BedrockRuntimeClient = boto3.client("bedrock-runtime", region_name=region)
    return client
