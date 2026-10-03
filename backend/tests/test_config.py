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
