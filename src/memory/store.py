"""Async SQLite store for interactions and document metadata."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.memory.models import Base, Document, Interaction

settings.db_path.parent.mkdir(parents=True, exist_ok=True)

_engine = create_async_engine(f"sqlite+aiosqlite:///{settings.db_path}", echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    """Create database tables if they do not exist."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    """Return an async SQLAlchemy session."""
    return _session_factory()


async def create_interaction_placeholder(query: str) -> int:
    """Create an empty interaction before generation starts."""
    async with get_session() as session:
        item = Interaction(
            query=query,
            answer="",
            retrieved_chunks={},
            model_used="",
            provider="",
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        session.add(item)
        await session.commit()
        return item.id


async def finalize_interaction(
    interaction_id: int,
    answer: str,
    retrieved_chunks: dict,
    model_used: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
) -> None:
    """Fill in a placeholder interaction."""
    async with get_session() as session:
        item = await session.get(Interaction, interaction_id)
        if item is None:
            return
        item.answer = answer
        item.retrieved_chunks = retrieved_chunks
        item.model_used = model_used
        item.provider = provider
        item.prompt_tokens = prompt_tokens
        item.completion_tokens = completion_tokens
        item.cost_usd = cost_usd
        item.latency_ms = latency_ms
        await session.commit()


async def mark_interaction_failed(interaction_id: int, error: str) -> None:
    """Mark an interaction as failed."""
    async with get_session() as session:
        item = await session.get(Interaction, interaction_id)
        if item is None:
            return
        item.answer = f"[ERROR] {error}"
        await session.commit()


async def set_feedback(interaction_id: int, feedback: int) -> None:
    """Set feedback for an interaction."""
    async with get_session() as session:
        item = await session.get(Interaction, interaction_id)
        if item is None:
            return
        item.user_feedback = feedback
        await session.commit()


async def get_recent_interactions(limit: int = 3) -> list[Interaction]:
    """Return recent successful interactions."""
    async with get_session() as session:
        result = await session.execute(
            select(Interaction)
            .where(Interaction.answer != "")
            .where(~Interaction.answer.startswith("[ERROR]"))
            .order_by(Interaction.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars())


async def list_interactions(page: int = 1, page_size: int = 20) -> tuple[list[Interaction], int]:
    """Return a page of interactions and total count."""
    async with get_session() as session:
        total = await session.scalar(select(func.count()).select_from(Interaction))
        result = await session.execute(
            select(Interaction)
            .order_by(Interaction.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars()), int(total or 0)


async def get_interaction(interaction_id: int) -> Interaction | None:
    """Get one interaction by id."""
    async with get_session() as session:
        return await session.get(Interaction, interaction_id)


async def upsert_document(
    source: str,
    source_type: str,
    title: str | None,
    chunk_count: int,
    file_hash: str,
) -> Document:
    """Insert or update an ingested document record."""
    async with get_session() as session:
        result = await session.execute(select(Document).where(Document.source == source))
        document = result.scalar_one_or_none()
        if document is None:
            document = Document(
                source=source,
                source_type=source_type,
                title=title,
                chunk_count=chunk_count,
                file_hash=file_hash,
            )
            session.add(document)
        else:
            document.source_type = source_type
            document.title = title
            document.chunk_count = chunk_count
            document.file_hash = file_hash
            document.ingested_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(document)
        return document


async def get_document_by_source(source: str) -> Document | None:
    """Get a document by source path."""
    async with get_session() as session:
        result = await session.execute(select(Document).where(Document.source == source))
        return result.scalar_one_or_none()


async def list_documents() -> list[Document]:
    """List ingested documents."""
    async with get_session() as session:
        result = await session.execute(select(Document).order_by(Document.ingested_at.desc()))
        return list(result.scalars())


async def delete_document_record(source: str) -> None:
    """Delete a document metadata record by source."""
    async with get_session() as session:
        await session.execute(delete(Document).where(Document.source == source))
        await session.commit()


async def is_unchanged(source: str, file_hash: str) -> bool:
    """Return True if source exists with the same file hash."""
    document = await get_document_by_source(source)
    return document is not None and document.file_hash == file_hash

