"""Tests for the Amazon Bedrock generator.

The Bedrock Runtime client is stubbed, so the adapter's request and response mapping is
covered without an AWS account. Nothing here proves that a real Bedrock call succeeds;
that needs credentials and a deployed model, and is stated as such in the README.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import GenerationFailedError
from app.rag import AnswerModel, AnswerRequest, BedrockAnswerModel, Passage


class _StubClient:
    """Records the calls the adapter makes and returns a canned response."""

    def __init__(
        self, response: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response if response is not None else _converse_response()
        self._error = error

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _converse_response(
    text: str = "Credentials rotate every ninety days. [1]",
    *,
    usage: dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content = blocks if blocks is not None else [{"text": text}]
    response: dict[str, Any] = {"output": {"message": {"role": "assistant", "content": content}}}
    if usage is not None:
        response["usage"] = usage
    return response


def _passage() -> Passage:
    return Passage(
        chunk_id="chunk-1",
        document_id="doc-1",
        document_name="policy.md",
        chunk_index=0,
        content="Credentials rotate every ninety days.",
        page_number=None,
        heading_path=("Rotation",),
        score=0.5,
    )


def _request() -> AnswerRequest:
    return AnswerRequest(
        question="How often do credentials rotate?",
        context="[1] policy.md — Rotation\nCredentials rotate every ninety days.",
        passages=(_passage(),),
    )


def test_the_bedrock_model_satisfies_the_answer_model_port() -> None:
    model = BedrockAnswerModel(model_id="test-model", client=_StubClient())

    assert isinstance(model, AnswerModel)
    assert model.kind == "generated"


def test_the_model_identifier_is_reported_as_the_name() -> None:
    model = BedrockAnswerModel(model_id="amazon.nova-lite-v1:0", client=_StubClient())

    assert model.name == "amazon.nova-lite-v1:0"


def test_it_sends_the_grounded_prompt_as_a_single_user_turn() -> None:
    client = _StubClient()

    BedrockAnswerModel(model_id="test-model", client=client).answer(_request())

    call = client.calls[0]
    assert call["modelId"] == "test-model"
    assert len(call["messages"]) == 1
    message = call["messages"][0]
    assert message["role"] == "user"
    prompt = message["content"][0]["text"]
    assert "only the numbered context passages" in prompt
    assert "[1] policy.md — Rotation" in prompt
    assert "Question: How often do credentials rotate?" in prompt


def test_it_passes_the_generation_limits_through() -> None:
    client = _StubClient()

    BedrockAnswerModel(
        model_id="test-model", client=client, max_tokens=256, temperature=0.3
    ).answer(_request())

    assert client.calls[0]["inferenceConfig"] == {"maxTokens": 256, "temperature": 0.3}


def test_it_returns_the_model_text_and_token_usage() -> None:
    client = _StubClient(
        _converse_response(usage={"inputTokens": 512, "outputTokens": 24, "totalTokens": 536})
    )

    answer = BedrockAnswerModel(model_id="test-model", client=client).answer(_request())

    assert answer.text == "Credentials rotate every ninety days. [1]"
    assert answer.input_tokens == 512
    assert answer.output_tokens == 24


def test_it_joins_multiple_content_blocks() -> None:
    client = _StubClient(_converse_response(blocks=[{"text": "First."}, {"text": " Second."}]))

    answer = BedrockAnswerModel(model_id="test-model", client=client).answer(_request())

    assert answer.text == "First. Second."


def test_missing_token_usage_is_reported_as_unknown_rather_than_zero() -> None:
    client = _StubClient(_converse_response())

    answer = BedrockAnswerModel(model_id="test-model", client=client).answer(_request())

    assert answer.input_tokens is None
    assert answer.output_tokens is None


def test_a_client_failure_becomes_a_generation_error() -> None:
    client = _StubClient(error=RuntimeError("AccessDeniedException"))

    with pytest.raises(GenerationFailedError, match="could not be reached") as failure:
        BedrockAnswerModel(model_id="test-model", client=client).answer(_request())

    assert isinstance(failure.value.__cause__, RuntimeError)


def test_an_empty_response_becomes_a_generation_error() -> None:
    client = _StubClient(_converse_response(blocks=[{"text": "   "}]))

    with pytest.raises(GenerationFailedError, match="no usable content"):
        BedrockAnswerModel(model_id="test-model", client=client).answer(_request())


def test_a_malformed_response_becomes_a_generation_error() -> None:
    client = _StubClient({"output": {}})

    with pytest.raises(GenerationFailedError, match="no usable content"):
        BedrockAnswerModel(model_id="test-model", client=client).answer(_request())


def test_the_aws_extra_is_needed_to_build_a_client() -> None:
    pytest.importorskip("boto3")

    model = BedrockAnswerModel(model_id="test-model", region="eu-west-1")

    assert model.name == "test-model"
