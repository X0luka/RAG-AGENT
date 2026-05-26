# 06 — Memory

**职责**:记录用户与系统的每次互动(行为日志)。第一版**不做语义记忆**,
只做"问过什么、答过什么、检索了什么、反馈如何"。

## 模块文件

```
src/memory/
├── __init__.py
├── models.py    # SQLAlchemy 模型(见 02-data-models.md 2.2 节)
└── store.py     # CRUD 操作
```

## 6.1 范围明确

### ✅ 第一版做

- 完整记录每次问答(query, answer, retrieved chunks, model, cost, latency)
- 用户反馈(thumb up/down,可选 0 表示已查看未评价)
- 记录摄入的文档列表
- 查询最近 N 条对话用于 prompt 上下文

### ❌ 第一版不做

- 从对话中抽取"事实"
- 用户画像 / 偏好建模
- 概念掌握度跟踪
- 间隔重复调度
- 记忆衰减 / 冲突解决

未来可能加入的高级 memory 能力,会作为独立模块(如 `src/memory_v2/`),
不污染当前简单设计。

## 6.2 数据库管理

### 初始化

```python
# src/memory/store.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

_engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.db_path}",
    echo=False,
)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    """创建表(若不存在)。幂等。在应用启动时调用。"""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    """获取 async session。使用方式:
    
        async with get_session() as session:
            ...
    """
    return _session_factory()
```

## 6.3 Interaction CRUD

```python
async def create_interaction_placeholder(query: str) -> int:
    """在生成开始前创建占位记录,返回 id。
    
    其他字段先用默认值或空字符串:
      - answer: ""
      - retrieved_chunks: {}
      - model_used: ""
      - provider: ""
      - prompt_tokens: 0
      - completion_tokens: 0
      - cost_usd: 0.0
      - latency_ms: 0
    
    timestamp 默认 = now(UTC)
    """


async def finalize_interaction(
    interaction_id: int,
    answer: str,
    retrieved_chunks: dict,    # {"ids": [...], "scores": [...], "sources": [...]}
    model_used: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
) -> None:
    """补全占位记录。"""


async def mark_interaction_failed(interaction_id: int, error: str) -> None:
    """标记 interaction 失败。answer 写 '[ERROR] {error}'。"""


async def set_feedback(interaction_id: int, feedback: int) -> None:
    """设置反馈,feedback ∈ {-1, 0, 1}。"""


async def get_recent_interactions(limit: int = 3) -> list[Interaction]:
    """获取最近 N 条 interaction,按 timestamp 倒序。
    
    用于 prompt 中的 history 上下文。
    
    重要:
    - 跳过失败的(answer 以 "[ERROR]" 开头)
    - 跳过 answer 为空的(未完成的)
    """


async def list_interactions(
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Interaction], int]:
    """分页查询。返回 (items, total_count)。"""


async def get_interaction(interaction_id: int) -> Interaction | None:
    pass
```

## 6.4 Document CRUD

```python
async def upsert_document(
    source: str,
    source_type: str,
    title: str | None,
    chunk_count: int,
    file_hash: str,
) -> Document:
    """插入或更新文档记录。
    
    若 source 已存在,更新所有字段(包括 ingested_at = now)。
    """


async def get_document_by_source(source: str) -> Document | None:
    pass


async def list_documents() -> list[Document]:
    pass


async def delete_document_record(source: str) -> None:
    pass


async def is_unchanged(source: str, file_hash: str) -> bool:
    """快速检查:source 已存在且 hash 相同。"""
```

## 6.5 一致性保证

### 与 Qdrant / BM25 的协调

`memory` 模块只管 SQLite。但摄入和删除时,需要保证三者一致:
- Qdrant
- BM25 索引
- SQLite documents 表

协调逻辑由 `src/ingestion/pipeline.py` 负责,见 `03-ingestion.md`。

### 失败容忍

`memory` 模块的写入失败**不应**导致主流程失败:

```python
# 在 generation/stream.py 中
try:
    await finalize_interaction(...)
except Exception as e:
    logger.error("Failed to write interaction: {err}", err=str(e))
    # 不 raise,继续给用户返回答案
```

## 6.6 在 Prompt 中使用 history

```python
# 由 generation 模块调用
recent = await get_recent_interactions(limit=settings.history_window)  # 默认 3
history_str = format_history_section(recent)
```

被引用的 `Interaction` 字段:
- `query`
- `answer`(用前需截断到 500 字符)

不要把 retrieved_chunks 也喂回给 LLM,只用问答对。

## 6.7 不在本模块的事

以下功能在其他模块,不要塞进 memory:

- 反馈触发的模型再训练 → 不做
- 自动给问题打标签 → 可未来加,放 `src/tagging/`
- 用户画像 → 不做
- 复习推荐 → 不做

---

*Related: [02-data-models.md](02-data-models.md), [05-generation.md](05-generation.md), [07-api.md](07-api.md)*
