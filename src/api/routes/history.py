"""Interaction history routes."""

from fastapi import APIRouter

from src.api.errors import DocumentNotFoundError
from src.api.schemas import HistoryDetail, HistoryItem, HistoryResponse
from src.memory.store import get_interaction, list_interactions

router = APIRouter(tags=["history"])


def _history_item(item) -> HistoryItem:
    return HistoryItem(
        id=item.id,
        timestamp=item.timestamp,
        query=item.query,
        answer=item.answer,
        feedback=item.user_feedback,
        cost_usd=item.cost_usd,
    )


@router.get("/history", response_model=HistoryResponse)
async def list_history(page: int = 1, page_size: int = 20) -> HistoryResponse:
    """List interaction history."""
    items, total = await list_interactions(page, page_size)
    return HistoryResponse(
        items=[_history_item(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/history/{interaction_id}", response_model=HistoryDetail)
async def get_history_item(interaction_id: int) -> HistoryDetail:
    """Get one interaction history item."""
    item = await get_interaction(interaction_id)
    if item is None:
        raise DocumentNotFoundError(f"interaction_id={interaction_id}")
    return HistoryDetail(
        **_history_item(item).model_dump(),
        retrieved_chunks=item.retrieved_chunks,
        model_used=item.model_used,
        provider=item.provider,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        latency_ms=item.latency_ms,
    )

