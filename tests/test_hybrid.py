"""Tests for reciprocal rank fusion."""

from src.retrieval import SearchResult
from src.retrieval.hybrid import reciprocal_rank_fusion


def _result(chunk_id: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        text=f"text {chunk_id}",
        score=score,
        payload={"source": "sample.pdf"},
    )


def test_rrf_two_lists_overlap() -> None:
    vector_results = [_result("id_A", 0.9), _result("id_B", 0.8), _result("id_C", 0.7)]
    bm25_results = [("id_B", 5.0), ("id_D", 4.0), ("id_A", 3.0)]

    fused = reciprocal_rank_fusion(vector_results, bm25_results, k=60)
    top_ids = {fused[0].chunk_id, fused[1].chunk_id}

    assert top_ids == {"id_A", "id_B"}


def test_rrf_single_list_only() -> None:
    vector_results = [_result("id_A", 0.9)]

    fused = reciprocal_rank_fusion(vector_results, [], k=60)

    assert fused[0].chunk_id == "id_A"
    assert fused[0].score == 1 / 61


def test_rrf_empty_inputs() -> None:
    assert reciprocal_rank_fusion([], [], k=60) == []

    fused = reciprocal_rank_fusion([], [("id_A", 1.0)], k=60)

    assert [result.chunk_id for result in fused] == ["id_A"]
