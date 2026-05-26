# Task 1.3 — Generation + End-to-End CLI

**Milestone**: M1
**Depends on**: task-1.2
**预计**: 1-2 天

## 目标

实现 LLM 调用层和流式问答管道,通过 CLI 跑通端到端 RAG。

## 必读文档

- [`../05-generation.md`](../05-generation.md) ← **主要参考**
- [`../06-memory.md`](../06-memory.md)(Interaction CRUD)
- [`../02-data-models.md`](../02-data-models.md)(StreamEvent / Citation)
- [`../08-observability.md`](../08-observability.md)

## 输出文件

```
src/generation/prompts.py
src/generation/llm.py
src/generation/stream.py
src/memory/store.py            # 补充 Interaction CRUD
src/observability/__init__.py  # setup_logging
scripts/ask.py                 # CLI 端到端
```

## 实现细节

### Prompts(`prompts.py`)

完整按 [`../05-generation.md`](../05-generation.md) 第 5.1 节实现。

包含:
- `SYSTEM_PROMPT` 常量
- `USER_PROMPT_TEMPLATE` 常量
- `format_history_section(history)` 函数
- `format_sources_section(chunks)` 函数
- `parse_citations(answer, chunks)` 函数

### LLM 客户端(`llm.py`)

完整按 [`../05-generation.md`](../05-generation.md) 第 5.2、5.3 节实现。

**关键**:
- 使用 `from langfuse.openai import AsyncOpenAI`(不是普通 openai)
- 两个 client 实例(DeepSeek、OpenRouter)模块级单例
- `call_llm` 和 `stream_llm` 两个函数
- `calculate_cost` 用价格表估算

### Stream 管道(`stream.py`)

完整按 [`../05-generation.md`](../05-generation.md) 第 5.4 节实现。

**关键**:
- `stream_query` 产出 StreamEvent 序列
- 占位 interaction → 流式生成 → 解析 citations → 补全 interaction
- SQLite 写入失败时只 log,不 raise

### Memory(`store.py` 增量)

按 [`../06-memory.md`](../06-memory.md) 第 6.3 节实现以下函数:
- `create_interaction_placeholder`
- `finalize_interaction`
- `mark_interaction_failed`
- `get_recent_interactions`

### CLI(`scripts/ask.py`)

```python
"""CLI: end-to-end RAG query.

Usage:
    uv run python scripts/ask.py "what is attention"
    uv run python scripts/ask.py "what is attention" --cheap
    uv run python scripts/ask.py "what is attention" --no-history
"""
import asyncio
import argparse
import sys
from src.observability import setup_logging
from src.observability.tracing import get_langfuse, shutdown_langfuse
from src.memory.store import init_db, get_recent_interactions
from src.retrieval.bm25 import bm25_index
from src.retrieval.rerank import retrieve_top_chunks
from src.generation.stream import stream_query


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--cheap", action="store_true", help="用 DeepSeek 替代 OpenRouter")
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()
    
    setup_logging()
    get_langfuse()
    await init_db()
    bm25_index.load()
    
    try:
        # 检索
        chunks = await retrieve_top_chunks(args.query)
        if not chunks:
            print("[ERROR] No chunks retrieved. 先用 ingest_one.py 喂入一些文档。")
            sys.exit(1)
        
        # 历史
        history = []
        if not args.no_history:
            history = await get_recent_interactions(limit=3)
        
        # 流式生成
        kind = "cheap" if args.cheap else "strong"
        citations_to_print = []
        async for event in stream_query(args.query, history, chunks, kind):
            if event.type == "start":
                print(f"\n[interaction_id={event.interaction_id}]\n")
            elif event.type == "delta":
                print(event.content, end="", flush=True)
            elif event.type == "citations":
                citations_to_print = event.citations or []
            elif event.type == "done":
                print(f"\n\n[Usage] tokens={event.usage['prompt_tokens']}+{event.usage['completion_tokens']}, "
                      f"cost=${event.usage['cost_usd']:.4f}, latency={event.latency_ms}ms")
            elif event.type == "error":
                print(f"\n[ERROR] {event.error_code}: {event.error_message}")
                sys.exit(1)
        
        # 打印引用
        if citations_to_print:
            print("\n[Citations]")
            for c in citations_to_print:
                page_str = f" p.{c.page}" if c.page else ""
                print(f"  [{c.source_id}] {c.source}{page_str}")
    finally:
        shutdown_langfuse()


if __name__ == "__main__":
    asyncio.run(main())
```

## Verify

```bash
# 前置:确认 task-1.1 已摄入至少 1 个文档
uv run python scripts/ingest_one.py data/raw/attention.pdf --type paper  # 若还没摄入

# 1. 端到端问答(强模型)
uv run python scripts/ask.py "what is self-attention"
# 期望:
#   - 看到流式输出
#   - 输出含 [source_N] 引用
#   - 末尾打印 usage 和 citations

# 2. 端到端问答(廉价模型)
uv run python scripts/ask.py "what is self-attention" --cheap
# 期望:同上,但 cost 更低

# 3. SQLite 中已记录
uv run python -c "
import asyncio
from src.memory.store import get_recent_interactions, init_db

async def main():
    await init_db()
    items = await get_recent_interactions(limit=5)
    for it in items:
        print(f'[{it.id}] {it.query[:50]}... → {it.answer[:80]}...')

asyncio.run(main())
"
# 期望:看到刚才的问答记录

# 4. Langfuse 中应有完整 trace
# 人工到 Langfuse 界面确认:
#   - 一条 query_pipeline trace
#   - 内含 retrieve_top_chunks 及其子 span
#   - 内含 chat.completions generation,有完整 input/output/usage
```

## Notes for Implementation

- `format_history_section` 注意:无历史时返回空字符串,**不要有多余换行**,否则 prompt 看起来很怪
- `parse_citations` 用正则 `r"\[source_(\d+)\]"`,匹配后去重排序
- LLM 流式响应中 usage 通常在最后一个 chunk,需要 `stream_options={"include_usage": True}`
- 占位 interaction 必须先于 LLM 调用创建,这样即使 LLM 失败也能在 SQLite 看到失败记录
- 不要在 stream_query 内部捕获并吞掉所有异常,部分异常应通过 error 事件传出

## 完成后

**M1 完成**。可以选择:
1. 继续 Task 2.1(评估闭环)→ 推荐,这是质量保证的关键
2. 或先做 Task 3.1(API)和 Task 3.2(UI)→ 想先有界面用着的话

推荐顺序:**Task 2.1 → Task 3.1 → Task 3.2**

---

*Related Tasks: [task-1.2-retrieval.md](task-1.2-retrieval.md), [task-2.1-eval.md](task-2.1-eval.md)*
