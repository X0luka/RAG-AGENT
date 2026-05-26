# Task 0.2 — LLM Connectivity Smoke Test

**Milestone**: M0
**Depends on**: task-0.1
**预计**: 0.5-1 小时

## 目标

验证 DeepSeek 和 OpenRouter 都能调通,Langfuse 能接收到 trace。

## 必读文档

- [`../05-generation.md`](../05-generation.md)
- [`../08-observability.md`](../08-observability.md)

## 输出文件

```
scripts/test_llm.py
```

## 实现规约

`scripts/test_llm.py`:

```python
"""LLM provider connectivity smoke test.

Usage:
    uv run python scripts/test_llm.py
    uv run python scripts/test_llm.py --provider deepseek
    uv run python scripts/test_llm.py --provider openrouter
"""
import asyncio
import argparse
import sys
from langfuse.openai import AsyncOpenAI
from src.config import settings
from src.observability.tracing import get_langfuse, shutdown_langfuse


async def test_deepseek():
    """测试 DeepSeek API。"""
    print("Testing DeepSeek...")
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    resp = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "user", "content": "Say 'hello from DeepSeek' in exactly those words."}
        ],
        max_tokens=50,
    )
    content = resp.choices[0].message.content
    print(f"  Response: {content}")
    print(f"  Tokens: prompt={resp.usage.prompt_tokens}, completion={resp.usage.completion_tokens}")
    assert content, "Empty response"
    print("  ✓ DeepSeek OK")


async def test_openrouter():
    """测试 OpenRouter API。"""
    print("Testing OpenRouter...")
    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_site_name,
        },
    )
    resp = await client.chat.completions.create(
        model=settings.openrouter_primary_model,
        messages=[
            {"role": "user", "content": "Say 'hello from OpenRouter' in exactly those words."}
        ],
        max_tokens=50,
    )
    content = resp.choices[0].message.content
    print(f"  Response: {content}")
    print(f"  Tokens: prompt={resp.usage.prompt_tokens}, completion={resp.usage.completion_tokens}")
    assert content, "Empty response"
    print("  ✓ OpenRouter OK")


async def test_streaming():
    """测试流式调用(用 DeepSeek,廉价)。"""
    print("Testing streaming (DeepSeek)...")
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    stream = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "user", "content": "Count from 1 to 5, one number per line."}
        ],
        max_tokens=50,
        stream=True,
        stream_options={"include_usage": True},
    )
    chunks_received = 0
    final_usage = None
    print("  Streaming: ", end="", flush=True)
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
            chunks_received += 1
        if chunk.usage:
            final_usage = chunk.usage
    print()  # newline
    print(f"  Chunks: {chunks_received}, Usage: {final_usage}")
    assert chunks_received > 0, "No chunks received"
    print("  ✓ Streaming OK")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        choices=["deepseek", "openrouter", "all"],
        default="all",
    )
    args = parser.parse_args()
    
    # 初始化 Langfuse(必须先初始化才能让 langfuse.openai 拦截工作)
    get_langfuse()
    
    try:
        if args.provider in ("deepseek", "all"):
            await test_deepseek()
        if args.provider in ("openrouter", "all"):
            await test_openrouter()
        if args.provider == "all":
            await test_streaming()
        
        print("\n所有测试通过 ✓")
        print(f"Langfuse host: {settings.langfuse_host}")
        print("请到 Langfuse 界面确认能看到上面的调用记录")
    finally:
        shutdown_langfuse()


if __name__ == "__main__":
    asyncio.run(main())
```

### `src/observability/tracing.py`

按 [`../08-observability.md`](../08-observability.md) 第 8.2 节实现最小版本:

```python
from langfuse import Langfuse
from src.config import settings

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


def shutdown_langfuse() -> None:
    if _langfuse:
        _langfuse.flush()
```

## Verify

```bash
# 1. 单独跑 DeepSeek
uv run python scripts/test_llm.py --provider deepseek
# 期望:看到 "✓ DeepSeek OK"

# 2. 单独跑 OpenRouter
uv run python scripts/test_llm.py --provider openrouter
# 期望:看到 "✓ OpenRouter OK"

# 3. 全部跑(含流式)
uv run python scripts/test_llm.py
# 期望:三个测试全过

# 4. 人工检查 Langfuse
# 打开 https://cloud.langfuse.com(或自托管地址)
# 进入项目 Traces,应能看到刚才的调用记录
```

## 故障排查指南

| 现象 | 可能原因 | 处理 |
|---|---|---|
| DeepSeek 401 | API key 错 | 检查 `.env` |
| DeepSeek 超时 | 网络问题 | WSL2 配 `networkingMode=mirrored`,不走代理 |
| OpenRouter 401 | API key 错或没充值 | 充值 $5 起步 |
| OpenRouter 404 | model 名字错 | 检查 https://openrouter.ai/models |
| Langfuse 无记录 | key 错 或 host 错 | 检查 `.env`,确认 host 没尾随斜杠 |
| 报错 `langfuse.openai` 找不到 | langfuse 版本太旧 | `uv add 'langfuse>=2.50'` |

## Notes for Implementation

- 这一步**只测连通性**,不要写业务逻辑
- `langfuse.openai.AsyncOpenAI` 是关键:不是 `from openai import AsyncOpenAI`,而是 `from langfuse.openai import AsyncOpenAI`,以便 Langfuse 自动埋点
- 若 Langfuse trace 没出现,可能是没调 `flush`。脚本中已经在 `finally` 调用了 `shutdown_langfuse()`

## 完成后

进入 Task 1.1。

---

*Related Tasks: [task-0.1-skeleton.md](task-0.1-skeleton.md), [task-1.1-ingestion.md](task-1.1-ingestion.md)*
