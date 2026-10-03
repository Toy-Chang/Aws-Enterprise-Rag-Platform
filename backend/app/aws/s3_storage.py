"""S3 implementation of the document storage port."""

from __future__ import annotations

from typing import Any, Protocol

from app.repositories.storage import DocumentStorageError


class S3Client(Protocol):
    """The S3 operations this adapter performs."""

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        """Upload an object."""
        ...

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        """Download an object."""
        ...

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        """Delete an object."""
        ...


class S3DocumentStorage:
    """Stores document content as objects under one prefix in one bucket.

    The key space is the one the filesystem adapter uses, and so are the keys it
    refuses: an empty key, an absolute one, a backslash or a ``..`` segment. A bucket
    has no root to escape, but a key that means something different to the caller than
    it does to the store is a bug waiting to happen, so both adapters reject the same
    input rather than one of them sanitising silently.

    Deleting a key that does not exist is not an error, which S3 already guarantees:
    ``DeleteObject`` is idempotent and answers 204 either way. That is the behaviour the
    port asks for, so it is passed through instead of being checked first.

    The client is injected so that the request mapping can be tested without an AWS
    account, and so that ``boto3`` is imported only when the adapter has to build its
    own client: the local deployment does not install the AWS SDK at all.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "documents",
        region: str | None = None,
        client: S3Client | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("bucket must not be empty")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client if client is not None else _create_client(region)

    @property
    def bucket(self) -> str:
        """The bucket objects are written to."""
        return self._bucket

    @property
    def prefix(self) -> str:
        """The key prefix objects are written under."""
        return self._prefix

    def save(self, key: str, content: bytes) -> None:
        object_key = self._object_key(key)
        try:
            self._client.put_object(Bucket=self._bucket, Key=object_key, Body=content)
        except Exception as exc:
            # Missing credentials, a bucket that is not there, a policy that denies the
            # write and a network failure are all the same thing to a caller: the
            # object could not be written. The detail is kept on the raised error,
            # which is logged rather than returned.
            raise DocumentStorageError(f"could not write object {key!r}") from exc

    def read(self, key: str) -> bytes:
        object_key = self._object_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            raise DocumentStorageError(f"could not read object {key!r}") from exc
        return _read_body(response)

    def delete(self, key: str) -> None:
        object_key = self._object_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            raise DocumentStorageError(f"could not delete object {key!r}") from exc

    def _object_key(self, key: str) -> str:
        """Map a storage key to an object key, refusing anything ambiguous."""
        if not key or key != key.strip() or key.startswith("/") or "\\" in key:
            raise DocumentStorageError(f"invalid storage key {key!r}")
        if any(part in {"", ".", ".."} for part in key.split("/")):
            raise DocumentStorageError(f"storage key {key!r} escapes the storage prefix")
        return f"{self._prefix}/{key}" if self._prefix else key


def _read_body(response: dict[str, Any]) -> bytes:
    """Return an object body as bytes.

    ``boto3`` hands back a ``StreamingBody``, which has to be read so the connection can
    be reused. Bytes and text are accepted too, which is what a test injects.
    """
    body = response.get("Body")
    if body is None:
        raise DocumentStorageError("the object response carried no body")
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")

    read = getattr(body, "read", None)
    if read is None:
        raise DocumentStorageError("the object body could not be read")
    return bytes(read())


def _create_client(region: str | None) -> S3Client:
    """Build an S3 client, or explain what is missing."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise RuntimeError(
            "the S3 storage adapter needs the AWS SDK: install the 'aws' extra "
            "(pip install -e '.[aws]') or set APP_STORAGE_BACKEND=local"
        ) from exc

    client: S3Client = boto3.client("s3", region_name=region)
    return client
