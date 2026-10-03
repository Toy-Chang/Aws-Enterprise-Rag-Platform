"""Tests for the numeric summaries behind the metrics and the evaluation report."""

from __future__ import annotations

import pytest

from app.core.statistics import mean, percentile, summarise


def test_percentile_uses_the_nearest_observed_rank() -> None:
    samples = [1.0, 2.0, 3.0, 4.0]

    assert percentile(samples, 0.25) == 1.0
    assert percentile(samples, 0.5) == 2.0
    assert percentile(samples, 0.51) == 3.0
    assert percentile(samples, 1.0) == 4.0


def test_percentile_never_reports_a_value_that_was_not_measured() -> None:
    """An interpolating definition would answer 1.5 here, which was never observed."""
    samples = [1.0, 2.0]

    assert percentile(samples, 0.5) in samples
    assert percentile(samples, 0.95) in samples


def test_percentile_of_a_single_sample_is_that_sample() -> None:
    assert percentile([7.5], 0.5) == 7.5
    assert percentile([7.5], 0.95) == 7.5


def test_percentile_does_not_require_sorted_input() -> None:
    assert percentile([4.0, 2.0, 3.0, 1.0], 0.95) == 4.0


@pytest.mark.parametrize("quantile", [0.0, -0.1, 1.5])
def test_percentile_rejects_an_impossible_quantile(quantile: float) -> None:
    with pytest.raises(ValueError, match="quantile"):
        percentile([1.0], quantile)


def test_percentile_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        percentile([], 0.5)


def test_summarise_reports_the_expected_statistics() -> None:
    summary = summarise([1.0, 2.0, 3.0, 4.0, 5.0])

    assert summary.count == 5
    assert summary.mean == 3.0
    assert summary.minimum == 1.0
    assert summary.p50 == 3.0
    assert summary.p95 == 5.0
    assert summary.maximum == 5.0


def test_summarise_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        summarise([])


def test_mean_is_rounded_for_reporting() -> None:
    assert mean([1.0, 2.0]) == 1.5
    assert mean([1.0, 2.0, 4.0]) == 2.333333


def test_mean_rejects_an_empty_sequence() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        mean([])
