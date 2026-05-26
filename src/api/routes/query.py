"""Query and feedback routes."""

import json
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.schemas import Citation, FeedbackRequest, QueryRequest, QueryResponse
from src.generation.stream import stream_query, sync_query
from src.memory.store import get_recent_interactions, set_feedback
from src.retrieval.bm25 import bm25_index
from src.retrieval.rerank import retrieve_top_chunks

router = APIRouter(tags=["query"])


def _citation_schema(citation) -> Citation:
    return Citation(
        source_id=citation.source_id,
        source=citation.source,
        page=citation.page,
        text_preview=citation.text_preview,
    )


async def _history_for(req: QueryRequest):
    if not req.include_history:
        return []
    return await get_recent_interactions(req.history_window)


@router.post("/query")
async def query_stream(req: QueryRequest) -> StreamingResponse:
    """Stream a RAG answer as server-sent events."""
    bm25_index.load()
    chunks = await retrieve_top_chunks(req.query)
    history = await _history_for(req)
    kind = "cheap" if req.use_cheap_model else "strong"

    async def generate():
        async for event in stream_query(req.query, history, chunks, kind):
            payload = asdict(event)
            yield f"event: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/query/sync", response_model=QueryResponse)
async def query_sync(req: QueryRequest) -> QueryResponse:
    """Run a non-streaming RAG query."""
    bm25_index.load()
    chunks = await retrieve_top_chunks(req.query)
    history = await _history_for(req)
    kind = "cheap" if req.use_cheap_model else "strong"
    response = await sync_query(req.query, history, chunks, kind)
    return QueryResponse(
        answer=response.answer,
        citations=[_citation_schema(citation) for citation in response.citations],
        interaction_id=response.interaction_id,
        latency_ms=response.latency_ms,
        cost_usd=response.cost_usd,
    )


@router.post("/feedback", status_code=204)
async def feedback_endpoint(req: FeedbackRequest) -> None:
    """Set feedback on an interaction."""
    await set_feedback(req.interaction_id, req.feedback)

