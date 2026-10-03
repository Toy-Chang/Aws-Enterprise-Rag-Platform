"""Tests for the hashing embedding adapter."""

from __future__ import annotations

import math

import pytest

from app.rag import HashingEmbeddingModel


def test_the_vector_has_the_configured_number_of_dimensions() -> None:
    model = HashingEmbeddingModel(dimensions=64)

    assert model.dimensions == 64
    assert len(model.embed_query("encryption policy")) == 64
    assert all(len(vector) == 64 for vector in model.embed_documents(["a", "b"]))


def test_vectors_are_unit_length() -> None:
    model = HashingEmbeddingModel(dimensions=128)

    vector = model.embed_query("rotate database credentials every ninety days")

    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)


def test_the_same_text_always_produces_the_same_vector() -> None:
    first = HashingEmbeddingModel(dimensions=256).embed_query("kms customer managed keys")
    second = HashingEmbeddingModel(dimensions=256).embed_query("kms customer managed keys")

    assert first == second


def test_document_and_query_embedding_agree_for_the_same_text() -> None:
    model = HashingEmbeddingModel(dimensions=256)

    assert model.embed_documents(["shared text"])[0] == model.embed_query("shared text")


def test_batching_preserves_order() -> None:
    model = HashingEmbeddingModel(dimensions=256)

    vectors = model.embed_documents(["alpha", "beta"])

    assert vectors == [model.embed_query("alpha"), model.embed_query("beta")]


def test_shared_vocabulary_scores_higher_than_unrelated_text() -> None:
    model = HashingEmbeddingModel(dimensions=512)
    query = model.embed_query("rotate database credentials")
    related = model.embed_query("database credentials rotate every ninety days")
    unrelated = model.embed_query("office seating plan and desk booking")

    def cosine(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=True))

    assert cosine(query, related) > cosine(query, unrelated)
    assert cosine(query, unrelated) == 0.0


def test_text_without_terms_produces_a_zero_vector() -> None:
    model = HashingEmbeddingModel(dimensions=32)

    assert model.embed_query("!!! ???") == [0.0] * 32
    assert model.embed_query("") == [0.0] * 32


def test_a_non_positive_dimension_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        HashingEmbeddingModel(dimensions=0)
