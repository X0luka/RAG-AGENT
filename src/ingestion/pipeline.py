"""End-to-end ingestion pipeline for source files."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from src.api.errors import IngestionFailedError
from src.config import settings
from src.ingestion.chunker import chunk_documents
from src.ingestion.loaders import auto_load
from src.memory.store import delete_document_record, get_document_by_source, upsert_document
from src.retrieval.bm25 import bm25_index
from src.retrieval.vector import embed_batch


@dataclass
class IngestResult:
    """Result of ingesting one document."""

    document_id: int
    chunk_count: int
    skipped: bool


def _source_for(path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.raw_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_filter(source: str) -> Filter:
    return Filter(
        must=[
            FieldCondition(
                key="source",
                match=MatchValue(value=source),
            )
        ]
    )


async def _ensure_collection(client: AsyncQdrantClient) -> None:
    exists = await client.collection_exists(settings.qdrant_collection)
    if not exists:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="source",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="source_type",
            field_schema=PayloadSchemaType.KEYWORD,
        )


async def _delete_qdrant_source(client: AsyncQdrantClient, source: str) -> None:
    if await client.collection_exists(settings.qdrant_collection):
        await client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=_source_filter(source),
        )


async def delete_document(source: str) -> None:
    """Delete a document and its Qdrant, BM25, and SQLite records."""
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=settings.request_timeout_seconds)
    await _delete_qdrant_source(client, source)
    bm25_index.load()
    bm25_index.remove_by_source(source)
    bm25_index.save()
    await delete_document_record(source)


async def ingest_file(path: Path, source_type: str, force: bool = False) -> IngestResult:
    """Ingest a file into Qdrant, BM25, and SQLite.

    Args:
        path: Source file to ingest.
        source_type: One of paper, code, article, or transcript.
        force: Reingest even if file hash is unchanged.

    Returns:
        Ingestion result with document id and chunk count.

    Raises:
        IngestionFailedError: If any ingestion stage fails.
    """
    source = _source_for(path)
    file_hash = _file_hash(path)
    existing = await get_document_by_source(source)
    if existing and existing.file_hash == file_hash and not force:
        return IngestResult(existing.id, existing.chunk_count, skipped=True)

    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=settings.request_timeout_seconds)
    stage = "prepare"
    try:
        if existing:
            await _delete_qdrant_source(client, source)
            bm25_index.load()
            bm25_index.remove_by_source(source)
            bm25_index.save()
            await delete_document_record(source)

        stage = "load"
        docs = auto_load(path, source_type)
        stage = "chunk"
        nodes = chunk_documents(docs, source_type)
        if not nodes:
            raise ValueError("No content extracted")

        stage = "embed"
        texts = [node.text for node in nodes]
        vectors = await embed_batch(texts, batch_size=100)

        stage = "index"
        await _ensure_collection(client)
        ingested_at = datetime.now(UTC).isoformat()
        point_ids = [uuid4().hex for _ in nodes]
        points = []
        for point_id, node, vector in zip(point_ids, nodes, vectors, strict=True):
            payload = {
                "text": node.text,
                "source": source,
                "source_type": source_type,
                "chunk_index": int(node.metadata["chunk_index"]),
                "heading_path": node.metadata.get("heading_path", []),
                "page": node.metadata.get("page"),
                "char_count": len(node.text),
                "ingested_at": ingested_at,
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        await client.upsert(collection_name=settings.qdrant_collection, points=points)

        bm25_index.load()
        bm25_index.add_documents(point_ids, texts, [source] * len(texts))
        bm25_index.save()

        stage = "store"
        title = path.stem
        document = await upsert_document(source, source_type, title, len(nodes), file_hash)
        return IngestResult(document.id, len(nodes), skipped=False)
    except Exception as exc:
        logger.exception("Failed to ingest {source} at {stage}", source=source, stage=stage)
        await _delete_qdrant_source(client, source)
        bm25_index.load()
        raise IngestionFailedError(source, stage, exc) from exc

