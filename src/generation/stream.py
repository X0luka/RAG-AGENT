"""Streaming and synchronous RAG answer generation pipelines."""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from src.api.errors import ErrorCode
from src.generation.llm import LLMUsage, ProviderKind, call_llm, stream_llm
from src.generation.prompts import (
    Citation,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_history_section,
    format_sources_section,
    parse_citations,
)
from src.memory.models import Interaction
from src.memory.store import (
    create_interaction_placeholder,
    finalize_interaction,
    mark_interaction_failed,
)
from src.observability.decorators import observe
from src.retrieval import SearchResult


@dataclass
class StreamEvent:
    """Event yielded by stream_query."""

    type: Literal["start", "delta", "citations", "done", "error"]
    interaction_id: int | None = None
    content: str | None = None
    citations: list[Citation] | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class QueryResponse:
    """Synchronous query response."""

    answer: str
    citations: list[Citation]
    interaction_id: int
    latency_ms: int
    cost_usd: float


def _build_user_prompt(query: str, history: list[Interaction], chunks: list[SearchResult]) -> str:
    return USER_PROMPT_TEMPLATE.format(
        history_section=format_history_section(history),
        sources_section=format_sources_section(chunks),
        query=query,
    )


def _retrieved_chunks_payload(chunks: list[SearchResult]) -> dict:
    return {
        "ids": [chunk.chunk_id for chunk in chunks],
        "scores": [chunk.score for chunk in chunks],
        "sources": [chunk.payload.get("source", "") for chunk in chunks],
    }


def _usage_dict(usage: LLMUsage | None) -> dict:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost_usd": usage.cost_usd,
    }


async def _safe_finalize(
    interaction_id: int,
    answer: str,
    chunks: list[SearchResult],
    usage: LLMUsage | None,
    latency_ms: int,
) -> None:
    try:
        await finalize_interaction(
            interaction_id=interaction_id,
            answer=answer,
            retrieved_chunks=_retrieved_chunks_payload(chunks),
            model_used=usage.model if usage else "",
            provider=usage.provider if usage else "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            cost_usd=usage.cost_usd if usage else 0.0,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.error("Failed to write interaction: {err}", err=str(exc))


@observe(name="query_pipeline")
async def stream_query(
    query: str,
    history: list[Interaction],
    chunks: list[SearchResult],
    kind: ProviderKind = "strong",
) -> AsyncIterator[StreamEvent]:
    """Stream a complete RAG answer."""
    started = time.perf_counter()
    interaction_id = await create_interaction_placeholder(query)
    yield StreamEvent(type="start", interaction_id=interaction_id)

    answer_parts: list[str] = []
    final_usage: LLMUsage | None = None
    try:
        user_prompt = _build_user_prompt(query, history, chunks)
        async for chunk in stream_llm(SYSTEM_PROMPT, user_prompt, kind):
            if chunk.delta:
                answer_parts.append(chunk.delta)
                yield StreamEvent(type="delta", content=chunk.delta)
            if chunk.done:
                final_usage = chunk.usage

        answer = "".join(answer_parts)
        citations = parse_citations(answer, chunks)
        latency_ms = int((time.perf_counter() - started) * 1000)
        yield StreamEvent(type="citations", citations=citations)
        await _safe_finalize(interaction_id, answer, chunks, final_usage, latency_ms)
        yield StreamEvent(
            type="done",
            usage=_usage_dict(final_usage),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.exception("Query pipeline failed for interaction {id}", id=interaction_id)
        await mark_interaction_failed(interaction_id, str(exc))
        yield StreamEvent(
            type="error",
            error_code=ErrorCode.LLM_ERROR,
            error_message=str(exc),
        )


@observe(name="query_pipeline")
async def sync_query(
    query: str,
    history: list[Interaction],
    chunks: list[SearchResult],
    kind: ProviderKind = "strong",
) -> QueryResponse:
    """Run a non-streaming RAG query."""
    started = time.perf_counter()
    interaction_id = await create_interaction_placeholder(query)
    try:
        user_prompt = _build_user_prompt(query, history, chunks)
        result = await call_llm(SYSTEM_PROMPT, user_prompt, kind)
        citations = parse_citations(result.content, chunks)
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _safe_finalize(interaction_id, result.content, chunks, result.usage, latency_ms)
        return QueryResponse(
            answer=result.content,
            citations=citations,
            interaction_id=interaction_id,
            latency_ms=latency_ms,
            cost_usd=result.usage.cost_usd,
        )
    except Exception as exc:
        await mark_interaction_failed(interaction_id, str(exc))
        raise

