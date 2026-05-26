"""Cohere reranking and top-level retrieval entrypoint."""

import cohere
from loguru import logger

from src.config import settings
from src.observability.decorators import observe
from src.retrieval import SearchResult
from src.retrieval.hybrid import hybrid_search

_cohere_client = cohere.AsyncClient(api_key=settings.cohere_api_key)


@observe(name="rerank")
async def rerank(query: str, candidates: list[SearchResult]) -> list[SearchResult]:
    """Rerank candidates with Cohere.

    Args:
        query: User query.
        candidates: Candidate chunks from hybrid search.

    Returns:
        Top reranked chunks, or a fallback slice if Cohere fails.
    """
    if not candidates:
        return []
    try:
        response = await _cohere_client.rerank(
            model=settings.rerank_model,
            query=query,
            documents=[candidate.text for candidate in candidates],
            top_n=min(settings.top_k_rerank, len(candidates)),
        )
        reranked = []
        for item in response.results:
            candidate = candidates[item.index]
            reranked.append(
                SearchResult(
                    chunk_id=candidate.chunk_id,
                    text=candidate.text,
                    score=float(item.relevance_score),
                    payload=dict(candidate.payload),
                )
            )
        return reranked
    except cohere.core.api_error.ApiError as exc:
        logger.warning("Cohere rerank failed: {err}", err=str(exc))
        return candidates[: settings.top_k_rerank]


@observe(name="retrieve_top_chunks")
async def retrieve_top_chunks(query: str) -> list[SearchResult]:
    """Retrieve top chunks via hybrid search and Cohere rerank."""
    candidates = await hybrid_search(query)
    return await rerank(query, candidates)
