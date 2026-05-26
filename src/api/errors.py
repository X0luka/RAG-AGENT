"""Shared API error schemas and business exceptions."""

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Structured error detail returned by API handlers."""

    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    """Top-level API error response."""

    error: ErrorDetail


class ErrorCode:
    """Stable API error code constants."""

    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_ALREADY_EXISTS = "DOCUMENT_ALREADY_EXISTS"
    INGESTION_FAILED = "INGESTION_FAILED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    LLM_ERROR = "LLM_ERROR"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    QDRANT_ERROR = "QDRANT_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class IngestionFailedError(Exception):
    """Raised when a document ingestion stage fails."""

    def __init__(self, source: str, stage: str, original: Exception) -> None:
        """Create an ingestion failure with source and stage context.

        Args:
            source: Source path being ingested.
            stage: Pipeline stage that failed.
            original: Original exception that caused the failure.
        """
        self.source = source
        self.stage = stage
        self.original = original
        super().__init__(f"Ingestion failed for {source} at {stage}: {original}")


class UnsupportedFileTypeError(Exception):
    """Raised when no loader supports a file extension."""

