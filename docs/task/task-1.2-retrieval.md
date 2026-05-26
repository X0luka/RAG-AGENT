# Task 1.2 — Retrieval Module

**Milestone**: M1
**Depends on**: task-1.1
**预计**: 1 天

## 目标

实现混合检索 + RRF + Cohere rerank,对外暴露 `retrieve_top_chunks`。

## 必读文档

- [`../04-retrieval.md`](../04-retrieval.md) ← **主要参考**
- [`../08-observability.md`](../08-observability.md)(span 装饰器)

## 输出文件

```
src/retrieval/__init__.py    # SearchResult dataclass + qdrant_client 单例
src/retrieval/vector.py      # 补充 vector_search(摄入侧的 embed_* 已在 task-1.1 实现)
src/retrieval/hybrid.py      # hybrid_search + reciprocal_rank_fusion
src/retrieval/rerank.py      # rerank + retrieve_top_chunks
tests/test_hybrid.py         # RRF 单元测试
```

## 实现细节

完整规约见 [`../04-retrieval.md`](../04-retrieval.md)。重点:

1. **SearchResult** 是 retrieval 模块的统一返回类型
2. **vector_search**:嵌入 query → Qdrant search → 转 SearchResult
3. **hybrid_search**:并发跑 vector + bm25,RRF 融合
4. **RRF**:对两个列表中的 chunk_id,计算 `sum(1/(k+rank))`,缺席列表的 rank 视为 top_k+1
5. **rerank**:调 Cohere,失败时降级返回原 candidates[:top_k]
6. **retrieve_top_chunks**:统一入口,内部 hybrid + rerank

### Langfuse Span 装饰

```python
from langfuse.decorators import observe

@observe(name="retrieve_top_chunks")
async def retrieve_top_chunks(query: str) -> list[SearchResult]:
    ...

@observe(name="hybrid_search")
async def hybrid_search(query: str) -> list[SearchResult]:
    ...

# vector_search, bm25 search 类似
```

### BM25-only 命中的 payload 回查

RRF 合并时,若某 chunk_id 只在 BM25 列表中,vector_results 没有它,
需要从 Qdrant 取 payload:

```python
needed_ids = [...]  # 只在 BM25 中的
points = await qdrant_client.retrieve(
    collection_name=settings.qdrant_collection,
    ids=needed_ids,
    with_payload=True,
)
# 构造 SearchResult
```

## Tests

### `tests/test_hybrid.py`

至少 3 个测试:

1. **test_rrf_two_lists_overlap**:
   - vector_results = [(id_A, 0.9), (id_B, 0.8), (id_C, 0.7)]
   - bm25_results = [(id_B, 5.0), (id_D, 4.0), (id_A, 3.0)]
   - 验证融合后 id_A 和 id_B 排在前(出现在两个列表中)
   
2. **test_rrf_single_list_only**:
   - vector_results 包含 id_A,bm25 不包含
   - 验证 id_A 仍然出现在结果中,score 为单边贡献

3. **test_rrf_empty_inputs**:
   - 两个都空 → 返回 [] 不报错
   - 一个空一个非空 → 返回非空列表的内容

**这些测试不需要真实 Qdrant 数据**,RRF 函数应该是纯函数,可以单测。

## Verify

```bash
# 1. 单元测试
uv run pytest tests/test_hybrid.py -v
# 期望:全过

# 2. 端到端检索(基于 task-1.1 已摄入的文档)
uv run python -c "
import asyncio
from src.retrieval.bm25 import bm25_index
from src.retrieval.rerank import retrieve_top_chunks

async def main():
    bm25_index.load()
    results = await retrieve_top_chunks('what is attention')
    for r in results:
        print(f'[{r.score:.3f}] {r.payload.get(\"source\")} | {r.text[:80]}...')

asyncio.run(main())
"
# 期望:打印至少 1 个相关结果(取决于已摄入内容)

# 3. Langfuse 中应能看到 retrieve_top_chunks 的 trace
# 人工到 Langfuse 界面确认
```

## Notes for Implementation

- Qdrant async client 在 `src/retrieval/__init__.py` 初始化为模块级单例
- Cohere client 同理,在 `rerank.py` 模块级
- 并发用 `asyncio.gather`,注意 BM25 是 sync 的,用 `asyncio.to_thread` 包一下
- Cohere rerank 在中文上效果可能一般,接受,M5 之后再考虑替换
- 不要为了"省 API 钱"而跳过 rerank,这是 RAG 质量的关键

## 完成后

进入 Task 1.3(generation + CLI 端到端)。

---

*Related Tasks: [task-1.1-ingestion.md](task-1.1-ingestion.md), [task-1.3-generation-cli.md](task-1.3-generation-cli.md)*
