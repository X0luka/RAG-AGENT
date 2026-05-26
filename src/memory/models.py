"""SQLAlchemy models for interactions and ingested documents."""

from datetime import UTC, datetime

from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class Interaction(Base):
    """一次用户问答记录。"""

    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        index=True,
        default=lambda: datetime.now(UTC),
    )
    query: Mapped[str]
    answer: Mapped[str]
    retrieved_chunks: Mapped[dict] = mapped_column(JSON)
    model_used: Mapped[str]
    provider: Mapped[str]
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    cost_usd: Mapped[float]
    user_feedback: Mapped[int | None] = mapped_column(default=None)
    latency_ms: Mapped[int]


class Document(Base):
    """已摄入文档的元数据。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(unique=True, index=True)
    source_type: Mapped[str]
    title: Mapped[str | None]
    chunk_count: Mapped[int]
    file_hash: Mapped[str]
    ingested_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

