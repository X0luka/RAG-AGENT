# 08 — Observability

**职责**:用 Langfuse 追踪所有 LLM 调用,用 loguru 记录应用日志。

## 模块文件

```
src/observability/
├── __init__.py
└── tracing.py
```

## 8.1 Langfuse 是什么

Langfuse 是一个 **LLM 应用可观测性平台**,不是 LLM 服务。它的工作方式:

```
应用代码 → Langfuse SDK → Langfuse 服务器 → Web UI
```

Langfuse 不替你调 LLM,它**在你的 LLM 调用前后插桩**,把"调了什么、收到什么、花了多少"上报到 Web UI,供你检索和分析。

### Key 含义

- `LANGFUSE_PUBLIC_KEY`(`pk-lf-...`): 标识项目
- `LANGFUSE_SECRET_KEY`(`sk-lf-...`): 签名上报数据
- 这两个 key 在 Langfuse 网页端创建项目时生成,不是任何 LLM 厂商给的

### Cloud vs 自托管

| 模式 | 配置 | 适用 |
|---|---|---|
| Cloud(默认) | `LANGFUSE_HOST=https://cloud.langfuse.com` | 轻量部署,开箱即用 |
| 自托管 | `LANGFUSE_HOST=http://localhost:3001`,docker compose 启 Langfuse | 数据完全本地 |

**第一阶段用 Cloud**,简单。后续按需切自托管。

## 8.2 `tracing.py`

```python
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context

# 全局单例
_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    """获取 Langfuse 客户端单例。"""
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


def shutdown_langfuse() -> None:
    """flush 所有 pending 数据。在应用关闭时调用。"""
    if _langfuse:
        _langfuse.flush()
```

## 8.3 集成方式:OpenAI SDK Wrapper

Langfuse 提供了 OpenAI SDK 的 wrapper,自动追踪所有调用:

```python
# 在 src/generation/llm.py 里
from langfuse.openai import AsyncOpenAI  # 注意是 langfuse.openai

_deepseek_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
)

_openrouter_client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url=settings.openrouter_base_url,
)
```

只要把 `from openai import AsyncOpenAI` 换成 `from langfuse.openai import AsyncOpenAI`,
**所有 chat.completions.create 自动被追踪**,不需要手动写埋点。

## 8.4 Trace 结构

每次 `/query` 应该是**一条 trace**,内部包含多个 span。

实现方式:用 `@observe()` 装饰器。

```python
from langfuse.decorators import observe, langfuse_context


@observe(name="query_pipeline")
async def run_query_pipeline(query: str, ...):
    """这个函数的整个执行 = 一条 trace。"""
    langfuse_context.update_current_trace(
        metadata={
            "query_length": len(query),
            "history_used": include_history,
        }
    )
    
    chunks = await retrieve_top_chunks(query)  # 内部 span
    async for event in stream_query(query, ..., chunks):  # 内部 span
        ...
```

retrieval 模块的 span:

```python
# src/retrieval/rerank.py
@observe(name="retrieve_top_chunks")
async def retrieve_top_chunks(query: str):
    ...

# src/retrieval/hybrid.py
@observe(name="hybrid_search")
async def hybrid_search(query: str):
    ...

@observe(name="vector_search")
async def vector_search(query: str, top_k: int):
    ...
```

`generation` 的 LLM 调用通过上面的 OpenAI wrapper 自动埋点,**不需要额外装饰**。

### 期望的 trace 视图(在 Langfuse Web UI)

```
trace: query_pipeline (id=xxx)
  metadata: {query_length: 35, history_used: true, num_sources: 8}
  total_latency: 4321ms
  total_cost: $0.0123
  │
  ├── span: retrieve_top_chunks (300ms)
  │     ├── span: hybrid_search (200ms)
  │     │     ├── span: vector_search (180ms)
      │     │     │     └── generation: aihubmix.embeddings (200ms, $0.0001)
  │     │     └── span: bm25_search (10ms)
  │     └── span: rerank (400ms)
  │
  └── generation: openai.chat.completions (3500ms, $0.012)
        input: <full prompt>
        output: <full response>
        usage: {prompt_tokens: 1234, completion_tokens: 567}
        model: anthropic/claude-sonnet-4.6
```

## 8.5 关联 interaction_id 到 trace

每次 query 时,把 SQLite 的 `interaction_id` 放到 trace metadata,
以便从 Langfuse UI 反查 SQLite 记录:

```python
langfuse_context.update_current_trace(
    metadata={"interaction_id": interaction_id, ...}
)
```

## 8.6 Self-RAG Trace 字段

`Task 4.2` 引入 LangGraph 后,每次 `/query` trace 需要额外记录:

- `rewrite_count`:最终 query 改写次数
- `retrieval_score`:最终检索质量分数
- `final_query`:最终用于生成的 query
- `retrieval_reason`:低分或通过评分的简短原因

Self-RAG 节点 span:

```text
span: self_rag_graph
  ├── span: retrieve_top_chunks
  ├── span: evaluate_retrieval
  ├── span: rewrite_query
  └── generation: openai.chat.completions
```

## 8.7 loguru 日志

`src/observability/__init__.py` 初始化 loguru:

```python
import sys
from loguru import logger
from src.config import settings


def setup_logging():
    """初始化 loguru:
    - 控制台:INFO 级别,彩色
    - 文件:DEBUG 级别,按日轮转,保留 14 天
    """
    logger.remove()  # 移除默认 handler
    
    # 控制台
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - {message}",
    )
    
    # 文件
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.log_path,
        level="DEBUG",
        rotation="00:00",
        retention="14 days",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
               "{name}:{function}:{line} - {message}",
    )


# 在 main.py 启动时调用
setup_logging()
```

## 8.8 使用模式

```python
from loguru import logger

# ✅ 用 {} 占位
logger.info("Ingesting {source} ({type})", source=path, type=source_type)

# ✅ 异常带 exception=True
try:
    ...
except Exception as e:
    logger.exception("Failed to ingest {source}", source=path)
    raise

# ❌ 不要 f-string
logger.info(f"Ingesting {path}")  # 失去结构化能力
```

## 8.9 性能注意

Langfuse SDK 默认是 **异步上报**(不阻塞主线程)。但应用退出时必须 flush:

```python
# src/api/main.py 的 lifespan 中
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 关闭时
    shutdown_langfuse()  # 确保所有 trace 上报
```

---

*Related: [01-config.md](01-config.md), [04-retrieval.md](04-retrieval.md), [05-generation.md](05-generation.md)*
