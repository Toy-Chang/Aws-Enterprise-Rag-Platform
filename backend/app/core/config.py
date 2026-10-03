"""Typed, environment-driven application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "production"]
LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Runtime settings for the API service.

    Values are resolved from ``APP_``-prefixed environment variables, then from an
    optional ``.env`` file in the working directory, then from the defaults
    declared here. Nothing is read from a committed file, so deployment platforms
    can inject configuration without code changes.
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity.
    name: str = "aws-enterprise-rag-platform"
    display_name: str = "AWS Enterprise RAG Platform"
    version: str = "0.1.0"
    environment: Environment = "local"
    api_version: str = "v1"
    api_v1_prefix: str = "/api/v1"

    # HTTP server.
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = False
    request_id_header: str = "X-Request-ID"

    # Persistence.
    database_url: str = "sqlite:///./rag.db"

    # Set when the process has to fetch its connection URL from Secrets Manager itself.
    # An ECS task definition resolves ``secrets.valueFrom`` before the container starts, so
    # the API never needs this; a Lambda has no equivalent, so the ingestion consumer is
    # configured with the secret's ARN and reads the URL out of it at cold start. The
    # password therefore stays out of a function configuration, which anyone with
    # ``lambda:GetFunctionConfiguration`` can read.
    database_secret_arn: str | None = None

    # Document storage (local adapter).
    storage_dir: str = "./data"
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1)

    # Ingestion. Chunk sizes are measured in characters: counting model tokens needs
    # the tokenizer of the model that will consume the text, which arrives with the
    # generation adapter.
    chunk_size_chars: int = Field(default=1200, ge=100)
    chunk_overlap_chars: int = Field(default=200, ge=0)
    embedding_dimensions: int = Field(default=256, ge=8)

    # Ingestion worker. The local stand-in for the queue and consumer that trigger
    # ingestion in the AWS deployment; tests disable it and drive the pipeline
    # directly so that no test depends on timing.
    ingestion_worker_enabled: bool = True
    ingestion_poll_seconds: float = Field(default=0.5, gt=0)
    ingestion_batch_size: int = Field(default=10, ge=1)

    # Retrieval. ``min_score`` is a policy rather than a property of the index: it
    # decides when the platform says the knowledge base does not cover a question
    # instead of answering from whatever came back. Its useful value depends on the
    # embedding model, so it has to be revisited when the model changes.
    retrieval_top_k: int = Field(default=5, ge=1, le=50)
    retrieval_min_score: float = Field(default=0.1, ge=-1.0, le=1.0)
    # Candidates fetched per requested passage when a reranker runs, so the reranker has
    # something to choose between rather than only reordering the final list.
    retrieval_candidate_multiplier: int = Field(default=4, ge=1, le=20)
    rerank_enabled: bool = False
    context_max_chars: int = Field(default=6000, ge=100)

    # Answer generation.
    generation_provider: Literal["local", "bedrock"] = "local"
    bedrock_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_region: str = "us-east-1"
    generation_max_tokens: int = Field(default=1024, ge=1)
    generation_temperature: float = Field(default=0.0, ge=0.0, le=1.0)

    # Observability.
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # AWS adapters. Each concern is selected independently, so a deployment can move one
    # at a time -- documents to S3 while embeddings stay local -- and the local stack
    # keeps needing no AWS credentials at all. A selection that is missing something it
    # needs is refused while the process starts, not at the first upload or question.
    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket: str | None = None
    s3_prefix: str = "documents"
    s3_region: str = "us-east-1"

    # Embeddings share ``bedrock_region`` with generation: both talk to Bedrock.
    embedding_provider: Literal["local", "bedrock"] = "local"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    vector_store_backend: Literal["memory", "opensearch"] = "memory"
    opensearch_endpoint: str | None = None
    opensearch_region: str = "us-east-1"
    opensearch_index: str = "rag-chunks"
    # With both of these set, requests carry basic authentication; with neither, they are
    # signed with SigV4 and the AWS SDK has to find credentials.
    opensearch_username: str | None = None
    opensearch_password: SecretStr | None = None
    opensearch_verify_certs: bool = True
    # A Serverless collection does not offer the nmslib engine and is signed with a
    # different service name, so the deployment has to say which kind it is.
    opensearch_serverless: bool = False

    # Ingestion work is handed to a queue, or not. The local stack has none: the worker
    # polls the database for pending documents. A deployment with more than one task
    # needs one, because two pollers would claim the same document; a deployment that
    # publishes has to turn ``ingestion_worker_enabled`` off for the same reason.
    queue_backend: Literal["none", "sqs"] = "none"
    sqs_queue_url: str | None = None
    sqs_region: str = "us-east-1"

    # Authentication. ``none`` leaves every endpoint open, which is what the local stack
    # and the container stack use; ``cognito`` verifies a bearer token against a user
    # pool and authorizes the caller by the groups the token carries. The production
    # environment refuses ``none``: see the validator below.
    auth_backend: Literal["none", "cognito"] = "none"
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_region: str = "us-east-1"
    # The issuer is derived from the pool and the region. This overrides it, which a
    # non-standard domain needs and a test finds convenient.
    cognito_issuer: str | None = None
    # How long the pool's key document is reused before it is fetched again, and how much
    # clock skew between this service and the pool is tolerated.
    cognito_jwks_cache_seconds: int = Field(default=3600, ge=0)
    auth_leeway_seconds: int = Field(default=60, ge=0)

    @property
    def authentication_enabled(self) -> bool:
        """Whether requests have to carry a verifiable token."""
        return self.auth_backend != "none"

    @property
    def cognito_issuer_url(self) -> str | None:
        """The issuer an accepted token has to carry, or ``None`` when auth is off."""
        if self.auth_backend != "cognito":
            return None
        configured = (self.cognito_issuer or "").strip()
        if configured:
            return configured
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
            f"{(self.cognito_user_pool_id or '').strip()}"
        )

    @property
    def opensearch_basic_auth(self) -> tuple[str, str] | None:
        """The basic-auth pair, or ``None`` when requests should be signed with SigV4."""
        if not self.opensearch_username or self.opensearch_password is None:
            return None
        password = self.opensearch_password.get_secret_value().strip()
        if not password:
            return None
        return self.opensearch_username, password

    @model_validator(mode="after")
    def _check_chunk_overlap(self) -> Settings:
        """Reject an overlap that would stop chunking from making progress."""
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")
        return self

    @model_validator(mode="after")
    def _check_aws_adapters(self) -> Settings:
        """Reject a backend selection that does not carry what it needs to start."""
        if self.storage_backend == "s3" and not (self.s3_bucket or "").strip():
            raise ValueError("s3_bucket is required when storage_backend is 's3'")

        if self.vector_store_backend == "opensearch":
            if not (self.opensearch_endpoint or "").strip():
                raise ValueError(
                    "opensearch_endpoint is required when vector_store_backend is 'opensearch'"
                )
            # A blank value is the same as an absent one: half a basic-auth pair would
            # otherwise look like a configuration and silently fall back to SigV4.
            self.opensearch_username = (self.opensearch_username or "").strip() or None
            if self.opensearch_password is not None and not (
                self.opensearch_password.get_secret_value().strip()
            ):
                self.opensearch_password = None
            if (self.opensearch_username is None) != (self.opensearch_password is None):
                raise ValueError(
                    "opensearch_username and opensearch_password have to be set together: "
                    "with neither of them, requests are signed with SigV4"
                )

        if self.queue_backend == "sqs" and not (self.sqs_queue_url or "").strip():
            raise ValueError("sqs_queue_url is required when queue_backend is 'sqs'")
        return self

    @model_validator(mode="after")
    def _check_authentication(self) -> Settings:
        """Refuse an authentication configuration that cannot protect the API."""
        if self.auth_backend == "cognito":
            if (
                not (self.cognito_user_pool_id or "").strip()
                and not (self.cognito_issuer or "").strip()
            ):
                raise ValueError(
                    "cognito_user_pool_id is required when auth_backend is 'cognito' "
                    "(or set cognito_issuer to the pool's issuer URL)"
                )
            if not (self.cognito_client_id or "").strip():
                raise ValueError("cognito_client_id is required when auth_backend is 'cognito'")

        # An open API in production is not a configuration to be warned about: it is the
        # difference between a platform and an exposed corpus.
        if self.auth_backend == "none" and self.environment == "production":
            raise ValueError(
                "auth_backend 'none' is refused in the production environment: "
                "set auth_backend=cognito with cognito_user_pool_id and cognito_client_id"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
