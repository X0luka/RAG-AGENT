# 07 — API

**职责**:用 FastAPI 暴露所有功能为 HTTP 接口。

## 模块文件

```
src/api/
├── __init__.py
├── main.py          # FastAPI app + lifespan
├── schemas.py       # Pydantic 模型(见 02-data-models.md)
├── errors.py        # 业务异常和错误码
└── routes/
    ├── __init__.py
    ├── ingest.py
    ├── query.py
    └── history.py
```

## 7.1 `main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化,关闭时清理。"""
    # 启动
    await init_db()                # 创建 SQLite 表
    await ensure_qdrant_collection()  # 创建 Qdrant collection(若不存在)
    bm25_index.load()              # 加载 BM25 索引
    yield
    # 关闭
    await _engine.dispose()


app = FastAPI(
    title="RAG Memory Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)

# 单用户本地项目,CORS 全开
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from src.api.routes import ingest, query, history
app.include_router(ingest.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(history.router, prefix="/api")


@app.get("/health")
async def health():
    """检查所有依赖连通性。
    
    返回:
        {
            "status": "ok" | "degraded",
            "checks": {
                "qdrant": "ok" | "error: ...",
                "sqlite": "ok" | "error: ...",
                "deepseek": "ok" | "error: ...",
                "openrouter": "ok" | "error: ..."
            }
        }
    
    检查方式:
    - qdrant: client.get_collections()
    - sqlite: SELECT 1
    - LLM: 不要每次都打 API(贵),只检查 client 是否初始化
    """
```

## 7.2 路由清单

### Ingest 路由(`routes/ingest.py`)

| Method | Path | 功能 |
|---|---|---|
| POST | `/api/ingest` | 摄入单个文件 |
| GET | `/api/documents` | 列出所有已摄入文档 |
| DELETE | `/api/documents/{id}` | 删除文档(连同 Qdrant + BM25) |

```python
from fastapi import APIRouter, HTTPException
router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(req: IngestRequest):
    """对应 ingestion.pipeline.ingest_file。"""


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents_endpoint():
    pass


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document_endpoint(document_id: int):
    """根据 id 查到 source,然后调用 pipeline.delete_document。"""
```

### Query 路由(`routes/query.py`)

| Method | Path | 功能 |
|---|---|---|
| POST | `/api/query` | SSE 流式问答 |
| POST | `/api/query/sync` | 非流式问答(供评估) |
| POST | `/api/feedback` | 提交反馈 |

```python
from fastapi.responses import StreamingResponse
import json

router = APIRouter(tags=["query"])


@router.post("/query")
async def query_stream(req: QueryRequest):
    """SSE 流式响应。
    
    流程:
    1. run_self_rag(req.query, ...) → chunks + answer stream
    2. 若 req.include_history:
       history = await get_recent_interactions(req.history_window)
       else: history = []
    3. kind = "cheap" if req.use_cheap_model else "strong"
    4. async generator:
       async for event in stream_query(req.query, history, chunks, kind):
           yield f"event: {event.type}\\ndata: {event.model_dump_json()}\\n\\n"
    
    Content-Type: text/event-stream
    
    返回 StreamingResponse(generator, media_type="text/event-stream")
    """


@router.post("/query/sync", response_model=QueryResponse)
async def query_sync(req: QueryRequest):
    """非流式版本,供评估。"""


@router.post("/feedback", status_code=204)
async def feedback_endpoint(req: FeedbackRequest):
    """设置反馈。"""
```

### History 路由(`routes/history.py`)

| Method | Path | 功能 |
|---|---|---|
| GET | `/api/history` | 分页查询互动历史 |
| GET | `/api/history/{id}` | 查单条互动详情 |

```python
@router.get("/history", response_model=HistoryResponse)
async def list_history(page: int = 1, page_size: int = 20):
    pass


@router.get("/history/{interaction_id}")
async def get_history_item(interaction_id: int):
    pass
```

## 7.3 SSE 协议详细

### 事件格式

每个事件块:

```
event: {type}
data: {json_payload}
\n
```

注意每个事件块以**两个换行符**结尾(SSE 标准)。

### 事件类型

见 `02-data-models.md` 的 `StreamEvent`。完整序列:

```
event: start
data: {"type":"start","interaction_id":42}

event: delta
data: {"type":"delta","content":"Attention"}

event: delta
data: {"type":"delta","content":" is a mechanism"}

...

event: citations
data: {"type":"citations","citations":[{"source_id":1,"source":"papers/attention.pdf","page":3,"text_preview":"..."}]}

event: done
data: {"type":"done","usage":{"prompt_tokens":1234,"completion_tokens":567,"cost_usd":0.0123},"latency_ms":4321}
```

错误时:

```
event: error
data: {"type":"error","error_code":"LLM_RATE_LIMITED","error_message":"..."}
```

### 客户端解析示例(Streamlit 用)

```python
import httpx
import json

async def stream_query(url: str, payload: dict):
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload) as response:
            event_type = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    yield event_type, data
```

## 7.4 错误响应

### 统一格式

所有 4xx / 5xx 响应:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document with id=42 not found",
    "details": null
  }
}
```

### 全局异常处理器

`main.py` 注册:

```python
from fastapi.requests import Request
from fastapi.responses import JSONResponse

@app.exception_handler(IngestionFailedError)
async def ingestion_error_handler(req: Request, exc: IngestionFailedError):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=ErrorDetail(
            code=ErrorCode.INGESTION_FAILED,
            message=f"Ingestion failed at stage '{exc.stage}': {exc.original}",
            details={"source": exc.source, "stage": exc.stage}
        )).model_dump()
    )

# 类似地处理其他业务异常
```

## 7.5 启动方式

```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI 文档自动在 `http://localhost:8000/docs`。

## 7.6 不在本模块

- 鉴权:本地优先部署阶段不做认证。如果以后部署上公网再加。
- 限流:同上。
- WebSocket:SSE 足够,不引入 WebSocket。

---

*Related: [02-data-models.md](02-data-models.md), [03-ingestion.md](03-ingestion.md), [05-generation.md](05-generation.md), [06-memory.md](06-memory.md)*
