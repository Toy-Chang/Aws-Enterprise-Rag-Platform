"""Tests for structured logging output."""

from __future__ import annotations

import io
import json

from app.core.config import Settings
from app.core.context import reset_request_id, set_request_id
from app.core.logging import configure_logging, get_logger


def test_json_records_carry_request_id_and_fields() -> None:
    stream = io.StringIO()
    configure_logging(Settings(_env_file=None, log_format="json", log_level="INFO"), stream=stream)
    token = set_request_id("req-123")
    try:
        get_logger("tests.logging").info("document_indexed", chunks=7)
    finally:
        reset_request_id(token)

    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "document_indexed"
    assert record["level"] == "info"
    assert record["logger"] == "tests.logging"
    assert record["request_id"] == "req-123"
    assert record["chunks"] == 7
    assert "timestamp" in record


def test_records_without_request_context_omit_request_id() -> None:
    stream = io.StringIO()
    configure_logging(Settings(_env_file=None, log_format="json", log_level="INFO"), stream=stream)
    get_logger("tests.logging").info("service_started")

    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "service_started"
    assert "request_id" not in record


def test_exception_information_is_rendered() -> None:
    stream = io.StringIO()
    configure_logging(Settings(_env_file=None, log_format="json", log_level="INFO"), stream=stream)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        get_logger("tests.logging").error("ingestion_failed", exc_info=exc)

    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "ingestion_failed"
    assert "ValueError: boom" in record["exception"]


def test_below_threshold_records_are_suppressed() -> None:
    stream = io.StringIO()
    configure_logging(
        Settings(_env_file=None, log_format="json", log_level="WARNING"), stream=stream
    )
    get_logger("tests.logging").info("ignored_event")

    assert stream.getvalue() == ""


def test_console_format_is_human_readable() -> None:
    stream = io.StringIO()
    configure_logging(
        Settings(_env_file=None, log_format="console", log_level="INFO"), stream=stream
    )
    get_logger("tests.logging").info("service_starting")

    output = stream.getvalue()
    assert "service_starting" in output
    assert not output.strip().startswith("{")
