"""CLI: 摄入单个文件到知识库。

Usage:
    uv run python scripts/ingest_one.py path/to/file.pdf --type paper
    uv run python scripts/ingest_one.py path/to/code.py --type code --force
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.pipeline import ingest_file
from src.memory.store import init_db
from src.retrieval.bm25 import bm25_index


async def main() -> None:
    """Parse CLI args and ingest one file."""
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

