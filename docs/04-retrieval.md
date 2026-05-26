# 04 — Retrieval

**职责**:对用户 query 做混合检索 + rerank,返回 top chunks 用于生成。

## 模块文件

```
src/retrieval/
├── __init__.py
├── vector.py    # Qdrant 向量检索
├── bm25.py      # BM25 关键词检索(摄入时也用,见 03-ingestion.md 3.4)
├── hybrid.py    # RRF 融合
└── rerank.py    # Cohere reranker
```

## 4.1 共享数据结构

放在 `src/retrieval/__init__.py`:

```python
from dataclasses import dataclass

@dataclass
class SearchResult:
    chunk_id: str           # Qdrant point id
    text: str               # chunk 原文
    score: float            # 当前阶段的分数
    payload: dict           # Qdrant payload(text, source, page 等)
```

## 4.2 `vector.py`

```python
async def vector_search(query: str, top_k: int) -> list[SearchResult]:
    """向量检索。
    
    流程:
    1. 调 AIHubMix OpenAI 兼容 embedding 接口(用 settings.embedding_model)
    2. Qdrant query_points,limit=top_k
    3. 转换为 SearchResult 列表,按 score 降序
    
    错误处理:
    - 嵌入失败重试 3 次(指数退避)
    - Qdrant 失败抛 QdrantError
    """


async def embed_text(text: str) -> list[float]:
    """单条文本嵌入。供 query 路径用。"""


async def embed_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """批量嵌入。供摄入路径用。"""
```

**Qdrant client 全局单例**(在 `src/retrieval/__init__.py`):

```python
from qdrant_client import AsyncQdrantClient
qdrant_client = AsyncQdrantClient(url=settings.qdrant_url)
```

## 4.3 `hybrid.py`

```python
import asyncio

async def hybrid_search(query: str) -> list[SearchResult]:
    """混合检索:向量 + BM25 + RRF 融合。
    
    流程:
    1. 并发执行:
       - vector_search(query, settings.top_k_vector)
       - bm25_index.search(query, settings.top_k_bm25)
    2. RRF 融合(见下)
    3. 按融合 score 排序,取前 settings.top_k_vector 个返回
    
    返回的 SearchResult.score 替换为 RRF 融合分数。
    """


def reciprocal_rank_fusion(
    vector_results: list[SearchResult],
    bm25_results: list[tuple[str, float]],
    k: int
) -> list[SearchResult]:
    """RRF 算法实现。
    
    Args:
        vector_results: 向量检索结果(已含完整 SearchResult)
        bm25_results: [(chunk_id, bm25_score), ...]
        k: RRF 参数(默认 60)
    
    Returns:
        融合后的 SearchResult 列表,按 RRF 分数降序
    
    算法:
        对每个出现在任一列表中的 chunk_id,
        rrf_score(d) = sum over lists of: 1 / (k + rank_in_list(d))
        
        若 chunk_id 只在一个列表中,另一个列表的贡献为 0(等价于无穷大 rank)。
        
        返回时合并去重,payload 和 text 用向量结果的(因为 BM25 没存 payload),
        若只在 BM25 中,需要回查 Qdrant 拿 payload。
    """
```

**实现细节**:
- BM25 索引中应该同时保存 raw_text,这样 RRF 阶段不用回查 Qdrant 取 text
- payload 信息(source / page 等)只有 Qdrant 有,所以 BM25-only 命中需要批量回查 Qdrant by point_ids
- 用 `client.retrieve(collection, ids=[...])` 批量回查

## 4.4 `rerank.py`

```python
import cohere

async def rerank(
    query: str,
    candidates: list[SearchResult]
) -> list[SearchResult]:
    """用 Cohere rerank 重排。
    
    流程:
    1. 调 Cohere rerank API:
       cohere.AsyncClient(api_key=settings.cohere_api_key).rerank(
           model=settings.rerank_model,
           query=query,
           documents=[c.text for c in candidates],
           top_n=settings.top_k_rerank
       )
    2. 按 Cohere 返回的 relevance_score 重组 SearchResult
    3. 返回 top settings.top_k_rerank 个
    
    输出的 SearchResult.score 替换为 Cohere 的 relevance_score(0-1)。
    
    错误处理:
    - Cohere 失败时降级:打 warning log,返回原 candidates[:top_k_rerank]
    - 不让 rerank 失败导致整个 query 失败
    """


async def retrieve_top_chunks(query: str) -> list[SearchResult]:
    """对外暴露的统一入口。
    
    流程:
    1. results = await hybrid_search(query)
    2. results = await rerank(query, results)
    3. return results
    
    这是 generation 模块调用的唯一检索接口。
    """
```

## 4.5 Langfuse 追踪

每次 `retrieve_top_chunks` 必须在一个 span 内,内部包含 4 个子 span:
- `vector_search`
- `bm25_search`
- `rrf_fusion`
- `rerank`

具体集成方式见 `08-observability.md`。

## 4.6 性能要求

单次 `retrieve_top_chunks` 在 chunks 总数 < 10000 时:
- P50 延迟 < 800ms
- P95 延迟 < 1500ms

主要延迟来源:
- AIHubMix embedding(query): ~200ms
- Qdrant search: ~50ms
- BM25 search(内存): ~10ms
- Cohere rerank: ~300-500ms

---

*Related: [02-data-models.md](02-data-models.md), [03-ingestion.md](03-ingestion.md), [05-generation.md](05-generation.md)*
