"""Tests for the Bedrock embedding adapter."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from app.aws.bedrock_embeddings import BedrockEmbeddingModel
from app.rag.embeddings import EmbeddingFailedError, EmbeddingModel


class StubBedrockRuntime:
    """A stand-in for the Bedrock Runtime client."""

    def __init__(self, *, vector: list[float] | None = None, body: Any = None, fail: bool = False):
        self.calls: list[dict[str, Any]] = []
        self._vector = vector if vector is not None else [0.5, 0.5]
        self._body = body
        self._fail = fail

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("AccessDeniedException")
        if self._body is not None:
            return {"body": self._body}
        return {"body": io.BytesIO(json.dumps({"embedding": self._vector}).encode("utf-8"))}

    @property
    def sent(self) -> dict[str, Any]:
        return json.loads(self.calls[-1]["body"])


def test_the_adapter_satisfies_the_embedding_port() -> None:
    model = BedrockEmbeddingModel(dimensions=2, client=StubBedrockRuntime())

    assert isinstance(model, EmbeddingModel)
    assert model.dimensions == 2
    assert model.model_id == "amazon.titan-embed-text-v2:0"


def test_the_request_carries_the_model_the_text_and_the_dimensions() -> None:
    client = StubBedrockRuntime()
    BedrockEmbeddingModel(
        dimensions=2, model_id="amazon.titan-embed-text-v2:0", client=client
    ).embed_query("how often do credentials rotate?")

    call = client.calls[0]
    assert call["modelId"] == "amazon.titan-embed-text-v2:0"
    assert call["accept"] == "application/json"
    assert call["contentType"] == "application/json"
    assert client.sent == {
        "inputText": "how often do credentials rotate?",
        "dimensions": 2,
        "normalize": True,
    }


def test_normalisation_can_be_turned_off() -> None:
    client = StubBedrockRuntime()
    BedrockEmbeddingModel(dimensions=2, normalize=False, client=client).embed_query("text")

    assert client.sent["normalize"] is False


def test_every_document_is_one_request_in_order() -> None:
    client = StubBedrockRuntime()
    vectors = BedrockEmbeddingModel(dimensions=2, client=client).embed_documents(
        ["one", "two", "three"]
    )

    # Titan has no batch operation, so this is deliberately one call per text.
    assert len(client.calls) == 3
    assert [json.loads(call["body"])["inputText"] for call in client.calls] == [
        "one",
        "two",
        "three",
    ]
    assert vectors == [[0.5, 0.5]] * 3


def test_an_empty_batch_makes_no_request() -> None:
    client = StubBedrockRuntime()

    assert BedrockEmbeddingModel(dimensions=2, client=client).embed_documents([]) == []
    assert client.calls == []


@pytest.mark.parametrize(
    "body",
    [
        io.BytesIO(json.dumps({"embedding": [0.25, 0.75]}).encode("utf-8")),
        json.dumps({"embedding": [0.25, 0.75]}).encode("utf-8"),
        json.dumps({"embedding": [0.25, 0.75]}),
    ],
)
def test_the_vector_is_read_from_the_shapes_a_client_returns(body: Any) -> None:
    # A stream is what boto3 returns; bytes and text are accepted so that the mapping can
    # be tested without one.
    client = StubBedrockRuntime(body=body)
    vector = BedrockEmbeddingModel(dimensions=2, client=client).embed_query("text")

    assert vector == [0.25, 0.75]


def test_a_vector_of_the_wrong_length_is_refused() -> None:
    client = StubBedrockRuntime(vector=[0.1, 0.2, 0.3])

    with pytest.raises(EmbeddingFailedError, match=r"returned 3 dimensions.*configured for 2"):
        BedrockEmbeddingModel(dimensions=2, client=client).embed_query("text")


def test_a_non_finite_value_is_refused() -> None:
    # One NaN would make every similarity it takes part in a NaN, and the ranking would
    # silently become meaningless rather than wrong in a visible way.
    client = StubBedrockRuntime(vector=[0.1, float("nan")])

    with pytest.raises(EmbeddingFailedError, match="non-finite"):
        BedrockEmbeddingModel(dimensions=2, client=client).embed_query("text")


def test_empty_text_is_refused_before_any_request() -> None:
    client = StubBedrockRuntime()

    with pytest.raises(EmbeddingFailedError, match="empty"):
        BedrockEmbeddingModel(dimensions=2, client=client).embed_query("   ")
    assert client.calls == []


def test_a_provider_failure_is_reported_as_an_embedding_failure() -> None:
    client = StubBedrockRuntime(fail=True)

    with pytest.raises(EmbeddingFailedError) as caught:
        BedrockEmbeddingModel(dimensions=2, client=client).embed_query("text")

    # A provider failure is a bad gateway rather than a crash of this service.
    assert caught.value.status_code == 502
    assert caught.value.code == "EMBEDDING_FAILED"
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize("body", [io.BytesIO(b"not json"), io.BytesIO(b"{}"), b""])
def test_a_response_without_an_embedding_is_refused(body: Any) -> None:
    client = StubBedrockRuntime(body=body)

    with pytest.raises(EmbeddingFailedError, match="no usable embedding"):
        BedrockEmbeddingModel(dimensions=2, client=client).embed_query("text")


def test_a_response_without_a_body_at_all_is_refused() -> None:
    with pytest.raises(EmbeddingFailedError, match="carried no body"):
        BedrockEmbeddingModel(dimensions=2, client=StubBedrockRuntime(body={})).embed_query("text")


def test_dimensions_have_to_be_positive() -> None:
    with pytest.raises(ValueError, match="dimensions must be positive"):
        BedrockEmbeddingModel(dimensions=0, client=StubBedrockRuntime())


def test_a_real_client_is_built_when_none_is_injected() -> None:
    # boto3 resolves a region and credentials lazily and makes no network call here, so
    # this asserts that the deferred import and the client wiring are correct.
    model = BedrockEmbeddingModel(dimensions=2, region="eu-west-1")

    assert model.dimensions == 2
