"""Typed, environment-driven application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # Observability.
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
