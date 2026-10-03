"""Tests for the local filesystem storage adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories.local_fs_storage import LocalFileSystemStorage
from app.repositories.storage import DocumentStorageError


def test_save_then_delete_round_trip(tmp_path: Path) -> None:
    storage = LocalFileSystemStorage(tmp_path)

    storage.save("knowledge-base/document", b"content")
    assert (tmp_path / "knowledge-base" / "document").read_bytes() == b"content"

    storage.delete("knowledge-base/document")
    assert not (tmp_path / "knowledge-base" / "document").exists()


def test_save_creates_missing_directories(tmp_path: Path) -> None:
    storage = LocalFileSystemStorage(tmp_path / "nested" / "root")

    storage.save("a/b/c", b"content")

    assert (tmp_path / "nested" / "root" / "a" / "b" / "c").read_bytes() == b"content"


def test_save_replaces_existing_content(tmp_path: Path) -> None:
    storage = LocalFileSystemStorage(tmp_path)

    storage.save("key", b"first")
    storage.save("key", b"second")

    assert (tmp_path / "key").read_bytes() == b"second"


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalFileSystemStorage(tmp_path)

    storage.delete("never/written")


@pytest.mark.parametrize("key", ["../escape", "nested/../../escape", "/absolute/path"])
def test_keys_cannot_escape_the_storage_root(tmp_path: Path, key: str) -> None:
    storage = LocalFileSystemStorage(tmp_path)

    with pytest.raises(DocumentStorageError):
        storage.save(key, b"content")


def test_constructing_the_adapter_does_not_touch_disk(tmp_path: Path) -> None:
    root = tmp_path / "not-created"

    LocalFileSystemStorage(root)

    assert not root.exists()


def test_a_storage_failure_is_reported_as_a_bad_gateway(tmp_path: Path) -> None:
    # The port's failure is a deliberate application error rather than a bare exception,
    # so a caller can tell "the storage backend will not give me this" from "this service
    # is broken".
    storage = LocalFileSystemStorage(tmp_path)

    with pytest.raises(DocumentStorageError) as caught:
        storage.read("does-not-exist")

    assert caught.value.status_code == 502
    assert caught.value.code == "STORAGE_ERROR"
