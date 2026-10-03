"""Tests for the S3 document storage adapter."""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.aws.s3_storage import S3DocumentStorage
from app.repositories.storage import DocumentStorage, DocumentStorageError


class StubS3:
    """A stand-in for the parts of the S3 client the adapter calls."""

    def __init__(self, *, body: Any = b"", fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._body = body
        self._fail = fail

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if self._fail:
            raise RuntimeError("the bucket is not there")

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self._record("put_object", kwargs)
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._record("get_object", kwargs)
        if self._body == "no-body":
            return {}
        return {"Body": self._body}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self._record("delete_object", kwargs)
        return {}


def test_the_adapter_satisfies_the_storage_port() -> None:
    assert isinstance(S3DocumentStorage("bucket", client=StubS3()), DocumentStorage)


def test_save_writes_the_object_under_the_prefix() -> None:
    client = StubS3()
    S3DocumentStorage("bucket", client=client).save("kb-1/doc-1", b"content")

    name, call = client.calls[0]
    assert name == "put_object"
    assert call == {"Bucket": "bucket", "Key": "documents/kb-1/doc-1", "Body": b"content"}


@pytest.mark.parametrize("prefix", ["documents", "/documents", "documents/", "/documents/"])
def test_the_prefix_is_normalised(prefix: str) -> None:
    client = StubS3()
    S3DocumentStorage("bucket", prefix=prefix, client=client).save("doc-1", b"content")

    assert client.calls[0][1]["Key"] == "documents/doc-1"


def test_an_empty_prefix_writes_the_key_as_it_is() -> None:
    client = StubS3()
    S3DocumentStorage("bucket", prefix="/", client=client).save("doc-1", b"content")

    assert client.calls[0][1]["Key"] == "doc-1"


def test_read_returns_the_object_body() -> None:
    client = StubS3(body=io.BytesIO(b"stored bytes"))
    stored = S3DocumentStorage("bucket", client=client).read("doc-1")

    assert stored == b"stored bytes"
    assert client.calls[0][1] == {"Bucket": "bucket", "Key": "documents/doc-1"}


@pytest.mark.parametrize(
    ("body", "expected"), [(b"raw bytes", b"raw bytes"), ("text body", b"text body")]
)
def test_read_accepts_a_body_that_is_not_a_stream(body: Any, expected: bytes) -> None:
    assert S3DocumentStorage("bucket", client=StubS3(body=body)).read("doc-1") == expected


def test_a_response_without_a_body_is_a_storage_error() -> None:
    with pytest.raises(DocumentStorageError, match="carried no body"):
        S3DocumentStorage("bucket", client=StubS3(body="no-body")).read("doc-1")


def test_delete_removes_the_object() -> None:
    client = StubS3()
    S3DocumentStorage("bucket", client=client).delete("doc-1")

    # Deleting a key that is not there is not an error: S3 answers 204 either way, which
    # is what the port asks for, so the adapter does not check first.
    assert client.calls == [("delete_object", {"Bucket": "bucket", "Key": "documents/doc-1"})]


@pytest.mark.parametrize("operation", ["save", "read", "delete"])
def test_a_client_failure_becomes_a_storage_error(operation: str) -> None:
    storage = S3DocumentStorage("bucket", client=StubS3(fail=True))

    with pytest.raises(DocumentStorageError, match="could not") as caught:
        if operation == "save":
            storage.save("doc-1", b"content")
        elif operation == "read":
            storage.read("doc-1")
        else:
            storage.delete("doc-1")

    # The SDK's own failure stays attached for the log rather than being flattened.
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "key",
    ["", "/absolute", "trailing/", "a/../b", "a//b", "a\\b", " leading", "trailing "],
)
def test_keys_that_are_not_plain_relative_paths_are_refused(key: str) -> None:
    storage = S3DocumentStorage("bucket", client=StubS3())

    with pytest.raises(DocumentStorageError):
        storage.save(key, b"content")


def test_an_empty_bucket_is_refused() -> None:
    with pytest.raises(ValueError, match="bucket must not be empty"):
        S3DocumentStorage("  ", client=StubS3())


def test_a_real_client_is_built_when_none_is_injected() -> None:
    # Constructing a boto3 client resolves a region and credentials lazily; it makes no
    # network call, so this asserts that the deferred import and the wiring are correct.
    storage = S3DocumentStorage("bucket", region="eu-west-1")

    assert storage.bucket == "bucket"
    assert storage.prefix == "documents"
