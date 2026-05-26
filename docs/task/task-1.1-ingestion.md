# Task 1.1 — Ingestion Module

**Milestone**: M1
**Depends on**: task-0.1, task-0.2
**预计**: 1-2 天

## 目标

完整实现摄入管道:加载 → 切块 → 嵌入 → 入 Qdrant + BM25 + SQLite。

## 必读文档

- [`../00-conventions.md`](../00-conventions.md)
- [`../01-config.md`](../01-config.md)
- [`../02-data-models.md`](../02-data-models.md)
- [`../03-ingestion.md`](../03-ingestion.md) ← **主要参考**
- [`../06-memory.md`](../06-memory.md)(只看 Document CRUD 部分)

## 输出文件

```
src/ingestion/loaders.py       # 文件加载
src/ingestion/chunker.py       # 切块
src/ingestion/pipeline.py      # 端到端
src/retrieval/bm25.py          # BM25 索引(摄入侧也用)
src/retrieval/vector.py        # embed_batch / embed_text 函数
src/memory/models.py           # SQLAlchemy 模型
src/memory/store.py            # 至少包含 Document CRUD + init_db
src/api/errors.py              # 异常类定义
scripts/ingest_one.py          # CLI 工具
tests/test_chunker.py          # 3 个测试
tests/test_bm25.py             # BM25 索引基础测试
```

## 实现细节

完整规约见 [`../03-ingestion.md`](../03-ingestion.md)。重点:

1. **loaders**:auto_load 按扩展名分派;PDF / MD / 代码 / HTML 各实现一个
2. **chunker**:代码走 CodeSplitter;其他走 MarkdownNodeParser + 二次 SentenceSplitter;
   metadata 必须含 `chunk_index` 和 `heading_path`
3. **pipeline**:hash 检查跳过、变更时回滚、批量嵌入(batch 100)、写 Qdrant + BM25 + SQLite
4. **BM25**:pickle 持久化,需同时保存 chunk_ids/sources/raw_texts/tokenized

### `scripts/ingest_one.py`

```python
"""CLI: 摄入单个文件到知识库。

Usage:
    uv run python scripts/ingest_one.py path/to/file.pdf --type paper
    uv run python scripts/ingest_one.py path/to/code.py --type code --force
"""
import argparse
import asyncio
from pathlib import Path
from src.ingestion.pipeline import ingest_file
from src.memory.store import init_db
from src.retrieval.bm25 import bm25_index


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--type",
        required=True,
        choices=["paper", "code", "article", "transcript"],
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    
    await init_db()
    bm25_index.load()
    
    result = await ingest_file(args.path, args.type, args.force)
    
    if result.skipped:
        print(f"✓ Skipped (unchanged): {args.path}")
        print(f"  Existing document_id={result.document_id}, chunks={result.chunk_count}")
    else:
        print(f"✓ Ingested: {args.path}")
        print(f"  document_id={result.document_id}, chunks={result.chunk_count}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Tests

### `tests/test_chunker.py`

至少 3 个测试:

1. **test_chunk_markdown_respects_headings**:喂一个带标题的 markdown,
   验证 chunks 的 `heading_path` 正确反映层级
2. **test_chunk_code_uses_code_splitter**:喂一段 Python 代码,
   验证用了 CodeSplitter(chunks 边界不在函数中间)
3. **test_chunk_index_increments**:验证 `chunk_index` 从 0 递增,无跳号

### `tests/test_bm25.py`

至少 2 个测试:

1. **test_add_and_search**:add 3 个文档,search 命中预期的一个
2. **test_remove_by_source**:add 后 remove,search 不再返回该 source 的内容

## Verify

```bash
# 1. 单元测试
uv run pytest tests/test_chunker.py tests/test_bm25.py -v
# 期望:全过

# 2. SQLite 初始化
uv run python -c "import asyncio; from src.memory.store import init_db; asyncio.run(init_db())"
# 期望:无错误,生成 data/memory.db

# 3. 摄入一个真实 PDF(用户提供任意 AI 论文)
uv run python scripts/ingest_one.py data/raw/sample.pdf --type paper
# 期望:打印 "✓ Ingested: ...",chunks > 0

# 4. Qdrant 中确实有 points
uv run python -c "
import asyncio
from qdrant_client import AsyncQdrantClient
from src.config import settings

async def check():
    c = AsyncQdrantClient(url=settings.qdrant_url)
    info = await c.get_collection(settings.qdrant_collection)
    print(f'points: {info.points_count}')

asyncio.run(check())
"
# 期望:points > 0

# 5. BM25 文件存在
ls -la data/processed/bm25.pkl
# 期望:文件存在

# 6. 重复摄入应跳过
uv run python scripts/ingest_one.py data/raw/sample.pdf --type paper
# 期望:打印 "✓ Skipped (unchanged)"
```

## Notes for Implementation

- 嵌入 API 调用走 `openai.AsyncOpenAI`,但 client 必须使用 `settings.aihubmix_api_key` 和 `settings.aihubmix_base_url`
- embedding 不是主问答 LLM call,不使用 langfuse wrapper
- LlamaIndex 的 `MarkdownNodeParser` 输出的 metadata 字段名是 `Header_1`/`Header_2`/`Header_3`,
  转成 `heading_path = ["title1", "title2"]` 列表
- CodeSplitter 需要 language 参数,不支持的语言会失败,扩展名映射需要兜底
- BM25 索引文件的父目录可能不存在,save 前 `mkdir(parents=True, exist_ok=True)`
- 测试用临时目录,不要污染 `data/`

## 完成后

进入 Task 1.2(retrieval)。

---

*Related Tasks: [task-1.2-retrieval.md](task-1.2-retrieval.md)*
