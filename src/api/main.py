"""FastAPI application for the RAG Memory Assistant."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from src.api.errors import (
    DocumentNotFoundError,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    IngestionFailedError,
    UnsupportedFileTypeError,
)
from src.api.routes import history, ingest, query
from src.config import settings
from src.memory.store import get_session, init_db
from src.observability import setup_logging
from src.observability.tracing import get_langfuse, shutdown_langfuse
from src.retrieval.bm25 import bm25_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local services and flush observability on shutdown."""
    del app
    setup_logging()
    await init_db()
    bm25_index.load()
    get_langfuse()
    yield
    shutdown_langfuse()


app = FastAPI(
    title="RAG Memory Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(history.router, prefix="/api")


def _error_response(status_code: int, code: str, message: str, details: dict | None = None):
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=message, details=details)
        ).model_dump(),
    )


@app.exception_handler(IngestionFailedError)
async def ingestion_error_handler(req: Request, exc: IngestionFailedError):
    """Handle ingestion failures."""
    del req
    return _error_response(
        500,
        ErrorCode.INGESTION_FAILED,
        f"Ingestion failed at stage '{exc.stage}': {exc.original}",
        {"source": exc.source, "stage": exc.stage},
    )


@app.exception_handler(UnsupportedFileTypeError)
async def unsupported_file_type_handler(req: Request, exc: UnsupportedFileTypeError):
    """Handle unsupported source files."""
    del req
    return _error_response(400, ErrorCode.UNSUPPORTED_FILE_TYPE, str(exc))


@app.exception_handler(DocumentNotFoundError)
async def document_not_found_handler(req: Request, exc: DocumentNotFoundError):
    """Handle missing documents and interactions."""
    del req
    return _error_response(404, ErrorCode.DOCUMENT_NOT_FOUND, str(exc))


@app.exception_handler(Exception)
async def internal_error_handler(req: Request, exc: Exception):
    """Handle unexpected errors."""
    del req
    return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))


@app.get("/health")
async def health() -> dict:
    """Check local service dependencies without calling LLM providers."""
    checks = {}
    try:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc}"

    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        checks["sqlite"] = "ok"
    except Exception as exc:
        checks["sqlite"] = f"error: {exc}"

    checks["deepseek"] = "configured" if settings.deepseek_api_key else "missing"
    checks["openrouter"] = "configured" if settings.openrouter_api_key else "missing"
    status = "ok" if all(value in {"ok", "configured"} for value in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
