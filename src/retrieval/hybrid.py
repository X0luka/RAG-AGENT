"""Hybrid retrieval with vector search, BM25, and reciprocal rank fusion."""

import asyncio

from src.config import settings
from src.observability.decorators import observe
from src.retrieval import SearchResult, qdrant_client
from src.retrieval.bm25 import bm25_index
from src.retrieval.vector import vector_search


@observe(name="bm25_search")
async def bm25_search(query: str, top_k: int) -> list[tuple[str, float]]:
    """Run BM25 search in a worker thread.

    Args:
        query: Query text.
        top_k: Maximum result count.

    Returns:
        Chunk id and score pairs.
    """
    return await asyncio.to_thread(bm25_index.search, query, top_k)


@observe(name="rrf_fusion")
def reciprocal_rank_fusion(
    vector_results: list[SearchResult],
    bm25_results: list[tuple[str, float]],
    k: int,
) -> list[SearchResult]:
    """Fuse vector and BM25 rankings with reciprocal rank fusion.

    Args:
        vector_results: Vector results with payloads.
        bm25_results: BM25 chunk id and score pairs.
        k: RRF smoothing constant.

    Returns:
        Deduplicated results sorted by fused score.
    """
    by_id = {result.chunk_id: result for result in vector_results}
    scores: dict[str, float] = {}
    order: dict[str, int] = {}

    for rank, result in enumerate(vector_results, start=1):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (k + rank)
        order.setdefault(result.chunk_id, len(order))

    for rank, (chunk_id, _score) in enumerate(bm25_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        order.setdefault(chunk_id, len(order))

    fused = []
    for chunk_id, score in scores.items():
        existing = by_id.get(chunk_id)
        if existing is None:
            existing = SearchResult(chunk_id=chunk_id, text="", score=0.0, payload={})
        fused.append(
            SearchResult(
                chunk_id=chunk_id,
                text=existing.text,
                score=score,
                payload=dict(existing.payload),
            )
        )
    return sorted(fused, key=lambda item: (-item.score, order[item.chunk_id]))


async def _hydrate_bm25_only(results: list[SearchResult]) -> list[SearchResult]:
    missing = [result.chunk_id for result in results if not result.payload]
    if not missing:
        return results
    points = await qdrant_client.retrieve(
        collection_name=settings.qdrant_collection,
        ids=missing,
        with_payload=True,
        with_vectors=False,
    )
    payloads = {str(point.id): dict(point.payload or {}) for point in points}
    hydrated = []
    for result in results:
        payload = payloads.get(result.chunk_id, result.payload)
        hydrated.append(
            SearchResult(
                chunk_id=result.chunk_id,
                text=result.text or str(payload.get("text", "")),
                score=result.score,
                payload=payload,
            )
        )
    return hydrated


@observe(name="hybrid_search")
async def hybrid_search(query: str) -> list[SearchResult]:
    """Run vector and BM25 search concurrently and fuse the rankings."""
    vector_results, bm25_results = await asyncio.gather(
        vector_search(query, settings.top_k_vector),
        bm25_search(query, settings.top_k_bm25),
    )
    fused = reciprocal_rank_fusion(vector_results, bm25_results, settings.rrf_k)
    hydrated = await _hydrate_bm25_only(fused)
    return hydrated[: settings.top_k_vector]
