"""Generate an evaluation golden set from ingested corpus chunks.

Usage:
    uv run python eval/generate_golden_set.py \
        --model anthropic/claude-opus-4.7 \
        --count 20 \
        --output eval/golden_set.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.retrieval.bm25 import bm25_index

DEFAULT_MODEL = "anthropic/claude-opus-4.7"
MAX_CONTEXT_CHARS = 45000


def _load_contexts(max_chars: int = MAX_CONTEXT_CHARS) -> list[dict[str, Any]]:
    bm25_index.load()
    if not bm25_index.raw_texts:
        raise RuntimeError("BM25 index is empty. Ingest documents before generating a golden set.")

    items = [
        {"source": source, "chunk_index": index, "text": text.strip()}
        for index, (source, text) in enumerate(
            zip(bm25_index.sources, bm25_index.raw_texts, strict=True),
        )
        if text.strip()
    ]
    items.sort(key=lambda item: (item["source"], item["chunk_index"]))

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    selected: list[dict[str, Any]] = []
    used_chars = 0
    sources = sorted(by_source)
    cursor = {source: 0 for source in sources}
    while sources and used_chars < max_chars:
        progressed = False
        for source in list(sources):
            source_items = by_source[source]
            if cursor[source] >= len(source_items):
                sources.remove(source)
                continue
            item = source_items[cursor[source]]
            cursor[source] += max(1, len(source_items) // 16)
            if used_chars + len(item["text"]) > max_chars:
                continue
            selected.append(item)
            used_chars += len(item["text"])
            progressed = True
        if not progressed:
            break

    if not selected:
        raise RuntimeError("No corpus context could be selected for golden set generation.")
    return selected


def _context_block(contexts: list[dict[str, Any]]) -> str:
    blocks = []
    for item in contexts:
        blocks.append(
            "\n".join(
                [
                    f"Source: {item['source']}",
                    f"Chunk: {item['chunk_index']}",
                    "Text:",
                    item["text"],
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def _prompt(count: int, contexts: list[dict[str, Any]]) -> str:
    sources = sorted({item["source"] for item in contexts})
    return f"""You are creating a high-quality golden evaluation set for a RAG system.

Use ONLY the corpus excerpts below. Generate exactly {count} evaluation items.

Requirements:
- Questions must be answerable from the provided excerpts.
- Use a mix of factual, comparative, synthesis, and why/how questions.
- Avoid trivial wording copied directly from headings.
- Ground truths must be concise but specific, and must not include unsupported claims.
- expected_sources must contain one or more exact source names from this list: {sources}
- difficulty must be one of: easy, medium, hard.
- tags must be short lowercase topic labels.
- Return valid JSON only, with this top-level shape:
  {{"items": [{{"id": "q001", "question": "...", "ground_truth": "...", "expected_sources": ["..."], "difficulty": "medium", "tags": ["..."]}}]}}

Corpus excerpts:
{_context_block(contexts)}
"""


def _parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_items(payload: dict[str, Any], count: int, sources: set[str]) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Generated payload must contain an 'items' list.")
    if len(raw_items) != count:
        raise ValueError(f"Expected {count} items, got {len(raw_items)}.")

    normalized = []
    seen_ids = set()
    required = {"question", "ground_truth", "expected_sources", "difficulty", "tags"}
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} must be an object.")
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Item {index} missing fields: {sorted(missing)}")

        item_id = f"q{index:03d}"
        expected_sources = item["expected_sources"]
        tags = item["tags"]
        if not isinstance(expected_sources, list) or not expected_sources:
            raise ValueError(f"{item_id} expected_sources must be a non-empty list.")
        if not set(expected_sources).issubset(sources):
            raise ValueError(f"{item_id} has unknown expected_sources: {expected_sources}")
        if item["difficulty"] not in {"easy", "medium", "hard"}:
            raise ValueError(f"{item_id} has invalid difficulty: {item['difficulty']}")
        if not isinstance(tags, list) or not tags:
            raise ValueError(f"{item_id} tags must be a non-empty list.")
        if item_id in seen_ids:
            raise ValueError(f"Duplicate item id: {item_id}")
        seen_ids.add(item_id)

        normalized.append(
            {
                "id": item_id,
                "question": str(item["question"]).strip(),
                "ground_truth": str(item["ground_truth"]).strip(),
                "expected_sources": [str(source).strip() for source in expected_sources],
                "difficulty": item["difficulty"],
                "tags": [str(tag).strip().lower() for tag in tags],
            }
        )
    return normalized


def generate_golden_set(model: str, count: int) -> list[dict[str, Any]]:
    contexts = _load_contexts()
    sources = {item["source"] for item in contexts}
    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_site_name,
        },
        timeout=settings.request_timeout_seconds,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON. Do not include markdown fences or commentary.",
            },
            {"role": "user", "content": _prompt(count, contexts)},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content or ""
    return _normalize_items(_parse_json(content), count, sources)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("eval/golden_set.json"))
    args = parser.parse_args()

    items = generate_golden_set(args.model, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} golden set items to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
