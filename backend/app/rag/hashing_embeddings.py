"""Dependency-free lexical embedding, used as the local development adapter."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence

from app.rag.text import terms


def _bucket(token: str, dimensions: int) -> int:
    """Hash a token to a bucket index.

    ``hashlib`` is used rather than the built-in :func:`hash` because the hash of a
    ``str`` is randomised per process: embeddings persisted by one process would not
    line up with embeddings computed by the next.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dimensions


class HashingEmbeddingModel:
    """A deterministic lexical embedding.

    Text is tokenised on word characters, every term is hashed into a fixed number of
    buckets with sublinear term-frequency weighting, and the vector is L2-normalised
    so that cosine similarity behaves like a term-overlap score. Identical text always
    produces an identical vector, in this process and in the next one.

    This is a *lexical* model, not a semantic one: it retrieves passages that share
    vocabulary with the query and knows nothing about meaning, paraphrase or synonyms.
    It exists so that ingestion and retrieval can run end to end, offline and
    deterministically, without pretending to be a neural encoder. The Amazon Bedrock
    embedding model implements the same port and replaces it in the AWS deployment.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        counts = Counter(terms(text))
        vector = [0.0] * self._dimensions
        for token, count in counts.items():
            # Sublinear weighting stops a term repeated many times from dominating the
            # vector the way a raw count would.
            vector[_bucket(token, self._dimensions)] += 1.0 + math.log(count)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
