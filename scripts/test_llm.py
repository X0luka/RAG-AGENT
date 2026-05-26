"""LLM provider connectivity smoke test.

Usage:
    uv run python scripts/test_llm.py
    uv run python scripts/test_llm.py --provider deepseek
    uv run python scripts/test_llm.py --provider openrouter
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langfuse.openai import AsyncOpenAI
from src.config import settings
from src.observability.tracing import get_langfuse, shutdown_langfuse


async def test_deepseek() -> None:
    """测试 DeepSeek API。"""
    print("Testing DeepSeek...")
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.request_timeout_seconds,
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


async def test_openrouter() -> None:
    """测试 OpenRouter API。"""
    print("Testing OpenRouter...")
    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.request_timeout_seconds,
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


async def test_streaming() -> None:
    """测试流式调用(用 DeepSeek,廉价)。"""
    print("Testing streaming (DeepSeek)...")
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.request_timeout_seconds,
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


async def main() -> None:
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
