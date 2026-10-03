"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_defaults_are_local_friendly() -> None:
    settings = Settings(_env_file=None)

    assert settings.name == "aws-enterprise-rag-platform"
    assert settings.environment == "local"
    assert settings.api_version == "v1"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.reload is False
    assert settings.request_id_header == "X-Request-ID"
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_PORT", "9001")
    monkeypatch.setenv("APP_LOG_FORMAT", "console")
    monkeypatch.setenv("APP_RELOAD", "true")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.port == 9001
    assert settings.log_format == "console"
    assert settings.reload is True


def test_unknown_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SOMETHING_UNRELATED", "value")

    settings = Settings(_env_file=None)

    assert not hasattr(settings, "something_unrelated")


@pytest.mark.parametrize("value", ["0", "70000", "-1"])
def test_out_of_range_port_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("APP_PORT", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unknown_log_format_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_FORMAT", "xml")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_ingestion_defaults_are_local_friendly() -> None:
    settings = Settings(_env_file=None)

    assert settings.chunk_size_chars == 1200
    assert settings.chunk_overlap_chars == 200
    assert settings.embedding_dimensions == 256
    assert settings.ingestion_worker_enabled is True
    assert settings.ingestion_poll_seconds == 0.5
    assert settings.ingestion_batch_size == 10


def test_an_overlap_that_is_not_smaller_than_the_chunk_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_CHUNK_SIZE_CHARS", "500")
    monkeypatch.setenv("APP_CHUNK_OVERLAP_CHARS", "500")

    with pytest.raises(ValidationError, match="chunk_overlap_chars"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("APP_CHUNK_SIZE_CHARS", "0"),
        ("APP_EMBEDDING_DIMENSIONS", "4"),
        ("APP_MAX_UPLOAD_SIZE_BYTES", "0"),
        ("APP_INGESTION_POLL_SECONDS", "0"),
        ("APP_INGESTION_BATCH_SIZE", "0"),
        ("APP_RETRIEVAL_TOP_K", "0"),
        ("APP_RETRIEVAL_TOP_K", "51"),
        ("APP_RETRIEVAL_MIN_SCORE", "1.5"),
        ("APP_RETRIEVAL_CANDIDATE_MULTIPLIER", "0"),
        ("APP_CONTEXT_MAX_CHARS", "10"),
        ("APP_GENERATION_MAX_TOKENS", "0"),
        ("APP_GENERATION_TEMPERATURE", "1.5"),
    ],
)
def test_out_of_range_ingestion_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_retrieval_defaults_are_local_friendly() -> None:
    settings = Settings(_env_file=None)

    assert settings.retrieval_top_k == 5
    assert settings.retrieval_min_score == 0.1
    assert settings.retrieval_candidate_multiplier == 4
    assert settings.context_max_chars == 6000
    # Reranking is off until Phase 5 can measure whether it improves anything.
    assert settings.rerank_enabled is False


def test_generation_defaults_to_the_local_extractive_adapter() -> None:
    settings = Settings(_env_file=None)

    assert settings.generation_provider == "local"
    assert settings.bedrock_model_id == "amazon.nova-lite-v1:0"
    assert settings.bedrock_region == "us-east-1"
    assert settings.generation_max_tokens == 1024
    assert settings.generation_temperature == 0.0


def test_an_unknown_generation_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_GENERATION_PROVIDER", "openai")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_generation_provider_can_be_switched_to_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_GENERATION_PROVIDER", "bedrock")
    monkeypatch.setenv("APP_BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")

    settings = Settings(_env_file=None)

    assert settings.generation_provider == "bedrock"
    assert settings.bedrock_model_id == "amazon.nova-pro-v1:0"
