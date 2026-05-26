"""CLI: end-to-end RAG query.

Usage:
    uv run python scripts/ask.py "what is attention"
    uv run python scripts/ask.py "what is attention" --cheap
    uv run python scripts/ask.py "what is attention" --no-history
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.generation.stream import stream_query
from src.memory.store import get_recent_interactions, init_db
from src.observability import setup_logging
from src.observability.tracing import get_langfuse, shutdown_langfuse
from src.retrieval.bm25 import bm25_index
from src.retrieval.rerank import retrieve_top_chunks


async def main() -> None:
    """Run an end-to-end RAG query from the command line."""
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
        chunks = await retrieve_top_chunks(args.query)
        if not chunks:
            print("[ERROR] No chunks retrieved. 先用 ingest_one.py 喂入一些文档。")
            sys.exit(1)

        history = []
        if not args.no_history:
            history = await get_recent_interactions(limit=3)

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
                usage = event.usage or {}
                print(
                    "\n\n[Usage] "
                    f"tokens={usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)}, "
                    f"cost=${usage.get('cost_usd', 0.0):.4f}, latency={event.latency_ms}ms"
                )
            elif event.type == "error":
                print(f"\n[ERROR] {event.error_code}: {event.error_message}")
                sys.exit(1)

        if citations_to_print:
            print("\n[Citations]")
            for citation in citations_to_print:
                page_str = f" p.{citation.page}" if citation.page else ""
                print(f"  [{citation.source_id}] {citation.source}{page_str}")
    finally:
        shutdown_langfuse()


if __name__ == "__main__":
    asyncio.run(main())
