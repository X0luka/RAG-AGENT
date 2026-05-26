"""Embedding helpers backed by the AIHubMix OpenAI-compatible API."""

import asyncio

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from src.config import settings
from src.observability.decorators import observe
from src.retrieval import SearchResult, qdrant_client

_embedding_client = AsyncOpenAI(
    api_key=settings.aihubmix_api_key,
    base_url=settings.aihubmix_base_url,
    timeout=settings.request_timeout_seconds,
)


async def _embed_with_retry(texts: list[str]) -> list[list[float]]:
    for attempt, delay in enumerate((1, 2, 4), start=1):
        try:
            response = await _embedding_client.embeddings.create(
                model=settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except (RateLimitError, APIConnectionError, APITimeoutError):
            if attempt == 3:
                raise
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable embedding retry state")


async def embed_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """Embed texts in batches.

    Args:
        texts: Texts to embed.
        batch_size: Batch size for embedding API calls.

    Returns:
        Embedding vectors aligned with input texts.
    """
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        embeddings.extend(await _embed_with_retry(texts[start : start + batch_size]))
    return embeddings


async def embed_text(text: str) -> list[float]:
    """Embed one text string.

    Args:
        text: Text to embed.

    Returns:
        Embedding vector.
    """
    return (await embed_batch([text], batch_size=1))[0]


@observe(name="vector_search")
async def vector_search(query: str, top_k: int) -> list[SearchResult]:
    """Search Qdrant by embedding the query.

    Args:
        query: User query text.
        top_k: Number of vector hits to return.

    Returns:
        Search results sorted by vector score.
    """
    vector = await embed_text(query)
    response = await qdrant_client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )
    results = []
    for point in response.points:
        payload = dict(point.payload or {})
        results.append(
            SearchResult(
                chunk_id=str(point.id),
                text=str(payload.get("text", "")),
                score=float(point.score),
                payload=payload,
            )
        )
    return results
