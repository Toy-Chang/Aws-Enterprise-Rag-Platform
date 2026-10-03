"""Information-retrieval metrics, computed from explicit relevance judgements.

Every number here comes from a judgement the caller supplied: which stored chunks
actually answer a question. Nothing is inferred from the text and no model decides
relevance, so a metric is only ever as good as the labels behind it.

The conventions are stated because they change the numbers:

* ``k`` is the number of results considered; everything after the first ``k`` is ignored.
* ``precision_at_k`` divides by ``k``, not by the number of results that came back. That
  is the standard definition, and it means a corpus too small to return ``k`` results
  caps precision accordingly rather than being flattered.
* Relevance is binary: a chunk is either labelled relevant for a question or it is not.
  Graded relevance would need graded labels, which nothing here produces.
* ``ndcg_at_k`` uses binary gains discounted by ``log2(rank + 1)``, and its ideal ranking
  is built from every labelled-relevant chunk, not only the retrieved ones. A chunk that
  appears twice is counted once: repetition is not extra evidence.
* A metric that would divide by zero raises instead of returning zero. An unanswerable
  question has no recall, and reporting 0.0 for it would silently count a label that does
  not exist as a failure to retrieve.

No faithfulness, groundedness or hallucination metric is computed anywhere in this
package. Those require human or model judgement of an answer's content, and this module
has neither; a lexical heuristic standing in for them would be a number with no meaning,
which is worse than an absent one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence, Set
from dataclasses import dataclass


def recall_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Return the fraction of labelled-relevant chunks found in the first ``k`` results."""
    _require_scoreable(k, relevant)
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def precision_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Return the fraction of the first ``k`` slots that hold a relevant chunk."""
    _require_scoreable(k, relevant)
    return len(set(retrieved[:k]) & relevant) / k


def hit_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Return 1.0 when any relevant chunk is in the first ``k`` results, else 0.0."""
    _require_scoreable(k, relevant)
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def reciprocal_rank(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Return 1/rank of the first relevant result, or 0.0 when none is in the first ``k``."""
    _require_scoreable(k, relevant)
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Return normalised discounted cumulative gain with binary gains."""
    _require_scoreable(k, relevant)

    seen: set[str] = set()
    gain = 0.0
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant and chunk_id not in seen:
            seen.add(chunk_id)
            gain += 1.0 / math.log2(rank + 1)

    ideal_hits = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return gain / ideal


def citation_precision(cited: Sequence[str], relevant: Set[str]) -> float:
    """Return the fraction of the chunks an answer cited that are labelled relevant."""
    if not cited:
        raise ValueError("citation precision is undefined without a citation")
    if not relevant:
        raise ValueError("citation precision is undefined without a relevant chunk")
    return len(set(cited) & relevant) / len(set(cited))


def citation_recall(cited: Sequence[str], relevant: Set[str]) -> float:
    """Return the fraction of the labelled-relevant chunks an answer cited."""
    if not relevant:
        raise ValueError("citation recall is undefined without a relevant chunk")
    return len(set(cited) & relevant) / len(relevant)


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    """Every retrieval metric of one question, computed over the first ``k`` results."""

    k: int
    relevant: int
    retrieved: int
    matched: int
    recall: float
    precision: float
    hit: float
    reciprocal_rank: float
    ndcg: float


def score_retrieval(retrieved: Sequence[str], relevant: Set[str], k: int) -> RetrievalScore:
    """Compute every retrieval metric for one question.

    ``retrieved`` is the ranking the pipeline produced, in order; ``relevant`` is the
    set of chunk ids the labels resolved to.
    """
    _require_scoreable(k, relevant)
    return RetrievalScore(
        k=k,
        relevant=len(relevant),
        retrieved=len(retrieved[:k]),
        matched=len(set(retrieved[:k]) & relevant),
        recall=recall_at_k(retrieved, relevant, k),
        precision=precision_at_k(retrieved, relevant, k),
        hit=hit_at_k(retrieved, relevant, k),
        reciprocal_rank=reciprocal_rank(retrieved, relevant, k),
        ndcg=ndcg_at_k(retrieved, relevant, k),
    )


def _require_scoreable(k: int, relevant: Set[str]) -> None:
    """Reject the inputs for which the metrics would be meaningless rather than zero."""
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant:
        raise ValueError("retrieval metrics are undefined without a relevant chunk")
