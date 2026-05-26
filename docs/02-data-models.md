# 02 — Data Models

## Qdrant Collection Schema

### Collection 配置

```python
collection_name = settings.qdrant_collection  # "documents"
vector_config = {
    "size": 1536,           # text-embedding-3-small
    "distance": "Cosine"
}
```

### Point Payload(必须严格遵守)

```python
{
    "text": str,                # chunk 原文,必填
    "source": str,              # 相对路径,如 "papers/attention.pdf",必填
    "source_type": Literal["paper", "code", "article", "transcript"],
    "chunk_index": int,         # 在该文档内的序号,从 0 起
    "heading_path": list[str],  # 标题路径,可为空 []
    "page": int | None,         # PDF 页码,非 PDF 为 None
    "char_count": int,          # chunk 字符数
    "ingested_at": str          # ISO 8601 UTC,如 "2026-05-25T10:00:00Z"
}
```

### Point ID

用 `uuid4().hex` 生成,字符串类型。**不要用文件名 + 序号拼接**,防止重摄入时冲突。

### 索引

为以下 payload 字段建索引,加速 filter:
- `source`(keyword index)
- `source_type`(keyword index)

```python
client.create_payload_index(
    collection_name=collection_name,
    field_name="source",
    field_schema=PayloadSchemaType.KEYWORD
)
```

## SQLite Schema

### 文件位置

`data/memory.db`,由 `settings.db_path` 控制。

### Tables

定义在 `src/memory/models.py`,使用 SQLAlchemy 2.0 风格。

```python
from datetime import datetime, UTC
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Interaction(Base):
    """一次用户问答记录。"""
    __tablename__ = "interactions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        index=True,
        default=lambda: datetime.now(UTC)
    )
    query: Mapped[str]
    answer: Mapped[str]
    retrieved_chunks: Mapped[dict] = mapped_column(JSON)
    # 格式: {"ids": [str], "scores": [float], "sources": [str]}
    
    model_used: Mapped[str]              # 完整模型字符串,如 "anthropic/claude-sonnet-4.6"
    provider: Mapped[str]                # "deepseek" / "openrouter"
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    cost_usd: Mapped[float]
    user_feedback: Mapped[int | None] = mapped_column(default=None)  # -1 / 0 / 1
    latency_ms: Mapped[int]


class Document(Base):
    """已摄入文档的元数据。"""
    __tablename__ = "documents"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(unique=True, index=True)
    source_type: Mapped[str]
    title: Mapped[str | None]
    chunk_count: Mapped[int]
    file_hash: Mapped[str]               # sha256 of file bytes
    ingested_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
```

### 数据库初始化

`src/memory/store.py` 提供:

```python
async def init_db() -> None:
    """创建表(若不存在)。在应用启动时调用,幂等。"""
    
async def get_session() -> AsyncSession:
    """获取 async session(用 async context manager)。"""
```

## API Schemas

定义在 `src/api/schemas.py`,所有 request/response 模型用 Pydantic v2。

### Ingest

```python
class IngestRequest(BaseModel):
    path: str                                  # 相对 data/raw/ 的路径
    source_type: Literal["paper", "code", "article", "transcript"]
    force: bool = False                        # 即使 hash 相同也重新摄入


class IngestResponse(BaseModel):
    document_id: int
    chunk_count: int
    skipped: bool                              # hash 命中已存在
    message: str
```

### Query

```python
class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    include_history: bool = True
    history_window: int = Field(default=3, ge=0, le=10)
    use_cheap_model: bool = False              # True 走 DeepSeek,False 走 OpenRouter


class Citation(BaseModel):
    source_id: int                             # prompt 中的 [source_N]
    source: str                                # 文件路径
    page: int | None
    text_preview: str                          # 前 200 字符


class QueryResponse(BaseModel):                # 非流式时(/query/sync)
    answer: str
    citations: list[Citation]
    interaction_id: int
    latency_ms: int
    cost_usd: float
```

### History

```python
class HistoryItem(BaseModel):
    id: int
    timestamp: datetime
    query: str
    answer: str
    feedback: int | None
    cost_usd: float


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class FeedbackRequest(BaseModel):
    interaction_id: int
    feedback: Literal[-1, 0, 1]
```

### Documents

```python
class DocumentItem(BaseModel):
    id: int
    source: str
    source_type: str
    title: str | None
    chunk_count: int
    ingested_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int
```

## SSE Event Types(流式查询)

```python
class StreamEvent(BaseModel):
    type: Literal["start", "delta", "citations", "done", "error"]
    
    # type=="start"
    interaction_id: int | None = None
    
    # type=="delta"
    content: str | None = None
    
    # type=="citations"
    citations: list[Citation] | None = None
    
    # type=="done"
    usage: dict | None = None      # {"prompt_tokens": int, "completion_tokens": int, "cost_usd": float}
    latency_ms: int | None = None
    
    # type=="error"
    error_code: str | None = None
    error_message: str | None = None
```

## Error Response 统一格式

定义在 `src/api/errors.py`。

```python
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
```

错误码常量(在 `src/api/errors.py`):

```python
class ErrorCode:
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
```

---

*Related: [00-conventions.md](00-conventions.md), [03-ingestion.md](03-ingestion.md), [07-api.md](07-api.md)*
