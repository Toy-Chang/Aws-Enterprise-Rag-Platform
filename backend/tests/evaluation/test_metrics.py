"""Tests for the retrieval metrics.

Every expected value here is computed from the definitions -- binary gains, discounting by
``log2(rank + 1)``, and an ideal ranking built from all the labelled-relevant chunks --
rather than from the implementation. A change to the implementation has to disagree with
arithmetic to pass.
"""

from __future__ import annotations

import pytest

from app.evaluation import (
    citation_precision,
    citation_recall,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_retrieval,
)

RANKING = ["a", "b", "c", "d"]


def test_recall_is_the_share_of_relevant_chunks_that_were_found() -> None:
    assert recall_at_k(RANKING, {"b", "d"}, 4) == 1.0
    assert recall_at_k(RANKING, {"b", "z"}, 4) == 0.5


def test_recall_ignores_results_beyond_k() -> None:
    assert recall_at_k(RANKING, {"d"}, 2) == 0.0
    assert recall_at_k(RANKING, {"d"}, 4) == 1.0


def test_precision_divides_by_k_rather_than_by_what_came_back() -> None:
    """The standard definition: a short result list is not flattered."""
    assert precision_at_k(["b"], {"b", "d"}, 4) == 0.25
    assert precision_at_k(RANKING, {"b", "d"}, 4) == 0.5


def test_a_repeated_result_is_not_extra_evidence() -> None:
    assert recall_at_k(["b", "b"], {"b", "d"}, 2) == 0.5
    assert precision_at_k(["b", "b"], {"b", "d"}, 2) == 0.5


def test_a_hit_is_about_presence_rather_than_rank() -> None:
    assert hit_at_k(RANKING, {"d"}, 4) == 1.0
    assert hit_at_k(RANKING, {"d"}, 3) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_result() -> None:
    assert reciprocal_rank(RANKING, {"a"}, 4) == 1.0
    assert reciprocal_rank(RANKING, {"b"}, 4) == 0.5
    assert reciprocal_rank(RANKING, {"c"}, 4) == pytest.approx(1 / 3)
    assert reciprocal_rank(RANKING, {"z"}, 4) == 0.0


def test_ndcg_matches_the_hand_computed_value() -> None:
    # DCG  = 1/log2(3) + 1/log2(5) = 1.0616063116448505
    # IDCG = 1/log2(2) + 1/log2(3) = 1.6309297535714575
    assert ndcg_at_k(RANKING, {"b", "d"}, 4) == pytest.approx(0.650920929807, abs=1e-9)


def test_ndcg_is_one_for_an_ideal_ranking() -> None:
    assert ndcg_at_k(["b", "d"], {"b", "d"}, 4) == 1.0


def test_ndcg_discounts_a_repeated_result_instead_of_counting_it_twice() -> None:
    # DCG = 1/log2(2) + 1/log2(4) = 1.5 against the same ideal as an unrepeated ranking.
    assert ndcg_at_k(["b", "b", "d"], {"b", "d"}, 3) == pytest.approx(0.919720789148, abs=1e-9)


def test_ndcg_uses_the_ideal_ranking_of_every_relevant_chunk() -> None:
    """One of three relevant chunks was found, and it sits second."""
    assert ndcg_at_k(["a", "b"], {"b", "c", "d"}, 2) == pytest.approx(0.386852807235, abs=1e-9)


def test_ndcg_is_zero_when_nothing_relevant_was_retrieved() -> None:
    assert ndcg_at_k(RANKING, {"z"}, 4) == 0.0
    assert ndcg_at_k([], {"b", "d"}, 4) == 0.0


def test_k_truncates_every_metric() -> None:
    retrieved = ["a", "a", "b"]

    assert recall_at_k(retrieved, {"b"}, 2) == 0.0
    assert ndcg_at_k(retrieved, {"b"}, 2) == 0.0
    assert ndcg_at_k(retrieved, {"b"}, 3) == 0.5


@pytest.mark.parametrize(
    "metric", [recall_at_k, precision_at_k, hit_at_k, reciprocal_rank, ndcg_at_k]
)
def test_a_metric_that_would_divide_by_zero_is_undefined_rather_than_zero(metric) -> None:
    """An unanswerable question has no recall; reporting 0.0 would invent a failure."""
    with pytest.raises(ValueError, match="without a relevant chunk"):
        metric(RANKING, set(), 4)


def test_a_non_positive_k_is_rejected() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        recall_at_k(RANKING, {"a"}, 0)


def test_score_retrieval_reports_every_metric_of_one_question() -> None:
    score = score_retrieval(RANKING, {"b", "d"}, 4)

    assert (score.k, score.relevant, score.retrieved, score.matched) == (4, 2, 4, 2)
    assert score.recall == 1.0
    assert score.precision == 0.5
    assert score.hit == 1.0
    assert score.reciprocal_rank == 0.5
    assert score.ndcg == pytest.approx(0.650920929807, abs=1e-9)


def test_a_score_over_nothing_retrieved_is_zero_but_for_the_label_count() -> None:
    score = score_retrieval([], {"b"}, 3)

    assert (score.retrieved, score.matched, score.relevant) == (0, 0, 1)
    assert (
        score.recall,
        score.precision,
        score.hit,
        score.reciprocal_rank,
        score.ndcg,
    ) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_citation_precision_asks_whether_what_was_cited_is_relevant() -> None:
    assert citation_precision(["b", "d"], {"b", "d"}) == 1.0
    assert citation_precision(["b", "z"], {"b", "d"}) == 0.5
    assert citation_precision(["z"], {"b"}) == 0.0


def test_citation_recall_asks_whether_the_evidence_was_cited() -> None:
    assert citation_recall(["b"], {"b", "d"}) == 0.5
    assert citation_recall(["b", "d"], {"b", "d"}) == 1.0


def test_citation_metrics_reject_the_cases_they_cannot_measure() -> None:
    with pytest.raises(ValueError, match="without a citation"):
        citation_precision([], {"b"})
    with pytest.raises(ValueError, match="without a relevant chunk"):
        citation_precision(["b"], set())
    with pytest.raises(ValueError, match="without a relevant chunk"):
        citation_recall(["b"], set())
