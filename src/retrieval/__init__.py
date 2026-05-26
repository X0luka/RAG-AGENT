"""Shared retrieval types and clients."""

from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient

from src.config import settings


@dataclass
class SearchResult:
    """Unified retrieval result returned by vector, hybrid, and rerank stages."""

    chunk_id: str
    text: str
    score: float
    payload: dict


qdrant_client = AsyncQdrantClient(
    url=settings.qdrant_url,
    timeout=settings.request_timeout_seconds,
)
