"""Document ingestion and document management routes."""

from pathlib import Path

from fastapi import APIRouter

from src.api.errors import DocumentNotFoundError
from src.api.schemas import DocumentItem, DocumentListResponse, IngestRequest, IngestResponse
from src.config import settings
from src.ingestion.pipeline import delete_document, ingest_file
from src.memory.store import list_documents

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(req: IngestRequest) -> IngestResponse:
    """Ingest a single file into the knowledge base."""
    path = Path(req.path)
    if not path.is_absolute() and not path.exists():
        path = settings.raw_dir / req.path
    result = await ingest_file(path, req.source_type, req.force)
    action = "Skipped unchanged" if result.skipped else "Ingested"
    return IngestResponse(
        document_id=result.document_id,
        chunk_count=result.chunk_count,
        skipped=result.skipped,
        message=f"{action}: {path}",
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents_endpoint() -> DocumentListResponse:
    """List ingested documents."""
    documents = await list_documents()
    items = [
        DocumentItem(
            id=document.id,
            source=document.source,
            source_type=document.source_type,
            title=document.title,
            chunk_count=document.chunk_count,
            ingested_at=document.ingested_at,
        )
        for document in documents
    ]
    return DocumentListResponse(items=items, total=len(items))


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document_endpoint(document_id: int) -> None:
    """Delete an ingested document by id."""
    documents = await list_documents()
    document = next((item for item in documents if item.id == document_id), None)
    if document is None:
        raise DocumentNotFoundError(f"document_id={document_id}")
    await delete_document(document.source)

