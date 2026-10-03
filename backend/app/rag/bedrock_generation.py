"""Amazon Bedrock answer generation behind the :class:`AnswerModel` port."""

from __future__ import annotations

from typing import Any, Protocol

from app.core.errors import GenerationFailedError
from app.rag.context import build_prompt
from app.rag.generation import AnswerRequest, GeneratedAnswer


class BedrockRuntimeClient(Protocol):
    """The one Bedrock Runtime operation this adapter performs."""

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        """Send a conversation turn to a model and return its response."""
        ...


class BedrockAnswerModel:
    """Generates answers with a Bedrock model through the Converse API.

    The client is injected so that the request and response mapping can be tested
    without an AWS account, and so that ``boto3`` is imported only when the adapter has
    to build its own client: the local deployment does not install the AWS SDK at all.

    Citations are not taken from the model's output. They are the passages the context
    was built from, which is why the prompt can ask for markers without the platform
    having to trust that the model used them correctly.
    """

    kind = "generated"

    def __init__(
        self,
        *,
        model_id: str,
        region: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        client: BedrockRuntimeClient | None = None,
    ) -> None:
        self._client = client if client is not None else _create_client(region)
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def name(self) -> str:
        """The model identifier, reported in the query trace."""
        return self._model_id

    def answer(self, request: AnswerRequest) -> GeneratedAnswer:
        prompt = build_prompt(request.question, request.context)
        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "maxTokens": self._max_tokens,
                    "temperature": self._temperature,
                },
            )
        except Exception as exc:
            # Credentials, throttling, an unknown model id and a network failure are all
            # the same thing to a caller: the answer could not be produced. The detail
            # is kept in the raised error, which the API layer logs rather than returns.
            raise GenerationFailedError(
                f"the model {self._model_id!r} could not be reached"
            ) from exc

        return GeneratedAnswer(
            text=_extract_text(response),
            input_tokens=_token_count(response, "inputTokens"),
            output_tokens=_token_count(response, "outputTokens"),
        )


def _extract_text(response: dict[str, Any]) -> str:
    """Pull the text out of a Converse response, or fail loudly."""
    try:
        blocks = response["output"]["message"]["content"]
        text = "".join(str(block.get("text", "")) for block in blocks).strip()
    except (AttributeError, KeyError, TypeError) as exc:
        raise GenerationFailedError("the model returned no usable content") from exc

    if not text:
        raise GenerationFailedError("the model returned no usable content")
    return text


def _token_count(response: dict[str, Any], key: str) -> int | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    return value if isinstance(value, int) else None


def _create_client(region: str | None) -> BedrockRuntimeClient:
    """Build a Bedrock Runtime client, or explain what is missing."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "the Bedrock generator needs the AWS SDK: install the 'aws' extra "
            "(pip install -e '.[aws]') or set APP_GENERATION_PROVIDER=local"
        ) from exc

    client: BedrockRuntimeClient = boto3.client("bedrock-runtime", region_name=region)
    return client
