"""Typed, environment-driven application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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

    # Observability.
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    @model_validator(mode="after")
    def _check_chunk_overlap(self) -> Settings:
        """Reject an overlap that would stop chunking from making progress."""
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
