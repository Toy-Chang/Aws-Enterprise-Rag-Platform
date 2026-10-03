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
    # Production refuses the permissive default, so a production-like environment has to
    # bring an identity provider with it.
    monkeypatch.setenv("APP_AUTH_BACKEND", "cognito")
    monkeypatch.setenv("APP_COGNITO_USER_POOL_ID", "eu-west-1_abc123")
    monkeypatch.setenv("APP_COGNITO_CLIENT_ID", "1a2b3c4d5e6f7g8h9i0j")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.port == 9001
    assert settings.log_format == "console"
    assert settings.reload is True
    assert settings.auth_backend == "cognito"


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


def test_aws_adapter_defaults_keep_the_platform_local() -> None:
    settings = Settings(_env_file=None)

    assert settings.storage_backend == "local"
    assert settings.s3_bucket is None
    assert settings.s3_prefix == "documents"
    assert settings.s3_region == "us-east-1"
    assert settings.embedding_provider == "local"
    assert settings.bedrock_embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.vector_store_backend == "memory"
    assert settings.opensearch_endpoint is None
    assert settings.opensearch_region == "us-east-1"
    assert settings.opensearch_index == "rag-chunks"
    assert settings.opensearch_username is None
    assert settings.opensearch_password is None
    assert settings.opensearch_verify_certs is True
    assert settings.opensearch_serverless is False
    assert settings.opensearch_basic_auth is None
    assert settings.queue_backend == "none"
    assert settings.sqs_queue_url is None
    assert settings.sqs_region == "us-east-1"


@pytest.mark.parametrize("bucket", ["", "   "])
def test_s3_without_a_bucket_is_rejected(bucket: str) -> None:
    with pytest.raises(ValidationError, match="s3_bucket is required"):
        Settings(_env_file=None, storage_backend="s3", s3_bucket=bucket)


def test_opensearch_without_an_endpoint_is_rejected() -> None:
    with pytest.raises(ValidationError, match="opensearch_endpoint is required"):
        Settings(_env_file=None, vector_store_backend="opensearch")


@pytest.mark.parametrize(
    "overrides",
    [
        {"opensearch_username": "platform"},
        {"opensearch_password": "secret"},
    ],
)
def test_half_a_basic_auth_pair_is_rejected(overrides: dict[str, str]) -> None:
    # Half a pair would look like a configuration and silently fall back to SigV4.
    with pytest.raises(ValidationError, match="have to be set together"):
        Settings(
            _env_file=None,
            vector_store_backend="opensearch",
            opensearch_endpoint="https://search.example.com",
            **overrides,
        )


def test_a_complete_basic_auth_pair_is_exposed_as_a_tuple() -> None:
    settings = Settings(
        _env_file=None,
        vector_store_backend="opensearch",
        opensearch_endpoint="https://search.example.com",
        opensearch_username="platform",
        opensearch_password="secret",
    )

    assert settings.opensearch_basic_auth == ("platform", "secret")


def test_blank_basic_auth_values_are_treated_as_absent() -> None:
    settings = Settings(
        _env_file=None,
        vector_store_backend="opensearch",
        opensearch_endpoint="https://search.example.com",
        opensearch_username="  ",
        opensearch_password="  ",
    )

    assert settings.opensearch_username is None
    assert settings.opensearch_password is None
    assert settings.opensearch_basic_auth is None


def test_the_opensearch_password_is_not_readable_from_a_representation() -> None:
    settings = Settings(
        _env_file=None,
        vector_store_backend="opensearch",
        opensearch_endpoint="https://search.example.com",
        opensearch_username="platform",
        opensearch_password="hunter2",
    )

    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage_backend", "gcs"),
        ("embedding_provider", "openai"),
        ("vector_store_backend", "pinecone"),
        ("queue_backend", "kafka"),
    ],
)
def test_an_unknown_adapter_is_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("queue_url", [None, "", "   "])
def test_sqs_without_a_queue_url_is_rejected(queue_url: str | None) -> None:
    with pytest.raises(ValidationError, match="sqs_queue_url is required"):
        Settings(_env_file=None, queue_backend="sqs", sqs_queue_url=queue_url)


def test_authentication_is_off_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.auth_backend == "none"
    assert settings.authentication_enabled is False
    assert settings.cognito_issuer_url is None
    assert settings.cognito_user_pool_id is None
    assert settings.cognito_client_id is None
    assert settings.cognito_region == "us-east-1"
    assert settings.cognito_issuer is None
    assert settings.cognito_jwks_cache_seconds == 3600
    assert settings.auth_leeway_seconds == 60


def test_cognito_needs_a_pool_and_a_client() -> None:
    with pytest.raises(ValidationError, match="cognito_user_pool_id is required"):
        Settings(_env_file=None, auth_backend="cognito")

    with pytest.raises(ValidationError, match="cognito_user_pool_id is required"):
        Settings(_env_file=None, auth_backend="cognito", cognito_client_id="client-id")

    with pytest.raises(ValidationError, match="cognito_client_id is required"):
        Settings(
            _env_file=None,
            auth_backend="cognito",
            cognito_user_pool_id="eu-west-1_TESTPOOL",
        )


def test_an_explicit_issuer_replaces_the_pool_id() -> None:
    settings = Settings(
        _env_file=None,
        auth_backend="cognito",
        cognito_client_id="client-id",
        cognito_issuer="https://login.example.com/pool",
    )

    assert settings.cognito_issuer_url == "https://login.example.com/pool"


def test_the_issuer_is_derived_from_the_pool_and_region() -> None:
    settings = Settings(
        _env_file=None,
        auth_backend="cognito",
        cognito_user_pool_id="eu-west-1_TESTPOOL",
        cognito_client_id="client-id",
        cognito_region="eu-west-1",
    )

    assert settings.authentication_enabled is True
    assert settings.cognito_issuer_url == (
        "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_TESTPOOL"
    )


def test_authentication_cannot_be_switched_off_in_production() -> None:
    # An open API in production is not a warning-level mistake: it is an exposed corpus.
    with pytest.raises(ValidationError, match="refused in the production environment"):
        Settings(_env_file=None, environment="production")

    settings = Settings(
        _env_file=None,
        environment="production",
        auth_backend="cognito",
        cognito_user_pool_id="eu-west-1_TESTPOOL",
        cognito_client_id="client-id",
    )
    assert settings.environment == "production"


def test_the_queue_backend_can_be_switched_to_sqs() -> None:
    settings = Settings(
        _env_file=None,
        queue_backend="sqs",
        sqs_queue_url=" https://sqs.eu-west-1.amazonaws.com/1/ingestion ",
        sqs_region="eu-west-1",
    )

    assert settings.queue_backend == "sqs"
    assert settings.sqs_region == "eu-west-1"
