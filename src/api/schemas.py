"""Pydantic schemas for the HTTP API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Request to ingest a source file."""

    path: str
    source_type: Literal["paper", "code", "article", "transcript"]
    force: bool = False


class IngestResponse(BaseModel):
    """Response from an ingest request."""

    document_id: int
    chunk_count: int
    skipped: bool
    message: str


class QueryRequest(BaseModel):
    """Request for RAG query endpoints."""

    query: str = Field(min_length=1, max_length=2000)
    include_history: bool = True
    history_window: int = Field(default=3, ge=0, le=10)
    use_cheap_model: bool = False


class Citation(BaseModel):
    """Citation returned by query endpoints."""

    source_id: int
    source: str
    page: int | None
    text_preview: str


class QueryResponse(BaseModel):
    """Non-streaming query response."""

    answer: str
    citations: list[Citation]
    interaction_id: int
    latency_ms: int
    cost_usd: float


class StreamEvent(BaseModel):
    """SSE event payload."""

    type: Literal["start", "delta", "citations", "done", "error"]
    interaction_id: int | None = None
    content: str | None = None
    citations: list[Citation] | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class FeedbackRequest(BaseModel):
    """Feedback request for an interaction."""

    interaction_id: int
    feedback: Literal[-1, 0, 1]


class HistoryItem(BaseModel):
    """History list item."""

    id: int
    timestamp: datetime
    query: str
    answer: str
    feedback: int | None
    cost_usd: float


class HistoryDetail(HistoryItem):
    """Detailed interaction history item."""

    retrieved_chunks: dict
    model_used: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class HistoryResponse(BaseModel):
    """Paginated history response."""

    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class DocumentItem(BaseModel):
    """Ingested document metadata."""

    id: int
    source: str
    source_type: str
    title: str | None
    chunk_count: int
    ingested_at: datetime


class DocumentListResponse(BaseModel):
    """Document list response."""

    items: list[DocumentItem]
    total: int

