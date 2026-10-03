"""Tests for the local reranker."""

from __future__ import annotations

from app.rag import LexicalOverlapReranker, Passage, Reranker


def _passage(chunk_id: str, content: str, score: float = 0.5) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        document_id="doc-1",
        document_name="policy.md",
        chunk_index=0,
        content=content,
        page_number=None,
        heading_path=(),
        score=score,
    )


def test_the_local_reranker_satisfies_its_port() -> None:
    assert isinstance(LexicalOverlapReranker(), Reranker)


def test_reranking_orders_by_question_coverage_not_by_similarity() -> None:
    frequent_term = _passage("a", "alpha " * 40, score=0.9)
    both_terms = _passage("b", "alpha beta", score=0.3)

    ordered = LexicalOverlapReranker().rerank("alpha beta", [frequent_term, both_terms])

    assert [passage.chunk_id for passage in ordered] == ["b", "a"]
    assert ordered[0].rerank_score == 1.0
    assert ordered[1].rerank_score == 0.5


def test_a_passage_that_shares_nothing_scores_zero() -> None:
    ordered = LexicalOverlapReranker().rerank("alpha beta", [_passage("a", "gamma delta")])

    assert ordered[0].rerank_score == 0.0


def test_equal_coverage_falls_back_to_the_retrieval_score() -> None:
    weaker = _passage("a", "alpha", score=0.2)
    stronger = _passage("b", "alpha", score=0.8)

    ordered = LexicalOverlapReranker().rerank("alpha", [weaker, stronger])

    assert [passage.chunk_id for passage in ordered] == ["b", "a"]


def test_a_full_tie_falls_back_to_the_chunk_identifier() -> None:
    ordered = LexicalOverlapReranker().rerank(
        "alpha", [_passage("zebra", "alpha"), _passage("alpha", "alpha")]
    )

    assert [passage.chunk_id for passage in ordered] == ["alpha", "zebra"]


def test_a_question_without_terms_leaves_the_order_untouched() -> None:
    passages = [_passage("a", "first", score=0.2), _passage("b", "second", score=0.9)]

    ordered = LexicalOverlapReranker().rerank("!!! ???", passages)

    assert [passage.chunk_id for passage in ordered] == ["a", "b"]
    assert all(passage.rerank_score is None for passage in ordered)


def test_reranking_returns_a_new_list_and_leaves_the_input_alone() -> None:
    passages = [_passage("a", "alpha"), _passage("b", "beta")]

    ordered = LexicalOverlapReranker().rerank("beta", passages)

    assert ordered is not passages
    assert [passage.chunk_id for passage in passages] == ["a", "b"]
    assert all(passage.rerank_score is None for passage in passages)


def test_reranking_is_reproducible() -> None:
    passages = [_passage("a", "alpha beta"), _passage("b", "alpha"), _passage("c", "beta")]

    first = LexicalOverlapReranker().rerank("alpha beta", passages)
    second = LexicalOverlapReranker().rerank("alpha beta", passages)

    assert [passage.chunk_id for passage in first] == [passage.chunk_id for passage in second]


def test_the_reranker_names_itself_for_the_trace() -> None:
    assert LexicalOverlapReranker().name == "lexical-overlap"
