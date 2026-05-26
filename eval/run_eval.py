"""Run RAG evaluation and archive results.

Usage:
    uv run python eval/run_eval.py --tag baseline-v0
"""

import argparse
import asyncio
import csv
import json
import sys
import time
import types
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.generation.stream import sync_query
from src.memory.store import init_db
from src.retrieval.bm25 import bm25_index
from src.retrieval.rerank import retrieve_top_chunks

THRESHOLDS = {
    "context_recall": 0.80,
    "context_precision": 0.70,
    "faithfulness": 0.85,
    "answer_relevancy": 0.80,
}

METRICS = ["context_recall", "context_precision", "faithfulness", "answer_relevancy"]


def _tokens(text: str) -> set[str]:
    return {
        token.strip(".,;:!?()[]{}\"'`").lower()
        for token in text.split()
        if len(token.strip(".,;:!?()[]{}\"'`")) > 3
    }


def _overlap_score(reference: str, candidate: str) -> float:
    reference_tokens = _tokens(reference)
    if not reference_tokens:
        return 0.0
    candidate_tokens = _tokens(candidate)
    return len(reference_tokens & candidate_tokens) / len(reference_tokens)


def _local_metric_rows(rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    metric_rows = []
    for row in rows:
        contexts_text = "\n".join(row["contexts"])
        context_recall = _overlap_score(row["ground_truth"], contexts_text)
        context_precision = sum(
            1 for context in row["contexts"] if _overlap_score(row["ground_truth"], context) > 0.05
        ) / max(len(row["contexts"]), 1)
        faithfulness = _overlap_score(row["answer"], contexts_text)
        answer_relevancy = _overlap_score(row["question"], row["answer"])
        metric_rows.append(
            {
                "context_recall": min(context_recall, 1.0),
                "context_precision": min(context_precision, 1.0),
                "faithfulness": min(faithfulness, 1.0),
                "answer_relevancy": min(answer_relevancy, 1.0),
            }
        )
    return metric_rows


def _install_ragas_vertexai_compat() -> None:
    """Install a shim for a removed langchain-community VertexAI import path."""
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    module = types.ModuleType(module_name)

    class ChatVertexAI:
        """Compatibility placeholder; this project does not use VertexAI."""

    module.ChatVertexAI = ChatVertexAI
    sys.modules[module_name] = module


def _ragas_models():
    _install_ragas_vertexai_compat()
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=settings.openrouter_primary_model,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_site_name,
            },
            temperature=0,
            timeout=settings.request_timeout_seconds,
        )
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.aihubmix_api_key,
            base_url=settings.aihubmix_base_url,
            timeout=settings.request_timeout_seconds,
        )
    )
    return llm, embeddings


def _try_ragas(rows: list[dict[str, Any]]) -> tuple[list[dict[str, float]], str]:
    try:
        _install_ragas_vertexai_compat()
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
        from datasets import Dataset

        dataset = Dataset.from_list(
            [
                {
                    "user_input": row["question"],
                    "response": row["answer"],
                    "retrieved_contexts": row["contexts"],
                    "reference": row["ground_truth"],
                }
                for row in rows
            ]
        )
        llm, embeddings = _ragas_models()
        result = evaluate(
            dataset,
            metrics=[context_recall, context_precision, faithfulness, answer_relevancy],
            llm=llm,
            embeddings=embeddings,
            raise_exceptions=False,
        )
        dataframe = result.to_pandas()
        metric_rows = [
            {metric: float(record.get(metric, 0.0)) for metric in METRICS}
            for record in dataframe.to_dict("records")
        ]
        return metric_rows, "ragas"
    except Exception as exc:
        print(f"[WARN] RAGAS unavailable, using local fallback metrics: {type(exc).__name__}: {exc}")
        return _local_metric_rows(rows), "local_fallback"


def _mean_metrics(metric_rows: list[dict[str, float]]) -> dict[str, float]:
    return {
        metric: sum(row[metric] for row in metric_rows) / max(len(metric_rows), 1)
        for metric in METRICS
    }


def _settings_snapshot() -> dict[str, Any]:
    return {
        "embedding_model": settings.embedding_model,
        "embedding_provider": "aihubmix",
        "rerank_model": settings.rerank_model,
        "openrouter_primary_model": settings.openrouter_primary_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k_vector": settings.top_k_vector,
        "top_k_bm25": settings.top_k_bm25,
        "top_k_rerank": settings.top_k_rerank,
        "rrf_k": settings.rrf_k,
        "temperature": settings.temperature,
    }


async def run_one(question_item: dict[str, Any]) -> dict[str, Any]:
    """Run one evaluation question through retrieval and sync generation."""
    started = time.perf_counter()
    chunks = await retrieve_top_chunks(question_item["question"])
    response = await sync_query(
        query=question_item["question"],
        history=[],
        chunks=chunks,
        kind="strong",
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "id": question_item["id"],
        "question": question_item["question"],
        "ground_truth": question_item["ground_truth"],
        "answer": response.answer,
        "contexts": [chunk.text for chunk in chunks],
        "difficulty": question_item["difficulty"],
        "tags": question_item["tags"],
        "expected_sources": question_item["expected_sources"],
        "retrieved_sources": [chunk.payload.get("source", "") for chunk in chunks],
        "cost_usd": response.cost_usd,
        "latency_ms": latency_ms,
    }


def _write_details(path: Path, rows: list[dict[str, Any]], metric_rows: list[dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id",
                "question",
                "difficulty",
                *METRICS,
                "cost_usd",
                "latency_ms",
                "retrieved_sources",
                "answer",
            ],
        )
        writer.writeheader()
        for row, metrics in zip(rows, metric_rows, strict=True):
            writer.writerow(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "difficulty": row["difficulty"],
                    **metrics,
                    "cost_usd": row["cost_usd"],
                    "latency_ms": row["latency_ms"],
                    "retrieved_sources": json.dumps(row["retrieved_sources"], ensure_ascii=False),
                    "answer": row["answer"],
                }
            )


def _print_previous_delta(results_dir: Path, tag: str, metrics: dict[str, float]) -> None:
    previous_scores = []
    for path in sorted(results_dir.glob("*/scores.json")):
        if path.parent.name == tag:
            continue
        try:
            previous_scores.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    if not previous_scores:
        return
    previous = previous_scores[-1]
    print("\nDelta vs previous:")
    for metric in METRICS:
        old = previous["metrics"].get(metric, 0.0)
        print(f"  {metric}: {metrics[metric]:.3f} ({metrics[metric] - old:+.3f})")


async def run_eval(tag: str, api_base: str = "http://localhost:8000") -> int:
    """Run evaluation and return an exit code."""
    del api_base
    started = time.perf_counter()
    golden_path = Path("eval/golden_set.json")
    questions = json.loads(golden_path.read_text(encoding="utf-8"))
    if not questions:
        print("[ERROR] eval/golden_set.json is empty")
        return 2

    await init_db()
    bm25_index.load()

    rows = []
    for index, item in enumerate(questions, start=1):
        try:
            row = await run_one(item)
        except Exception as exc:
            print(f"[ERROR] {item['id']} failed: {type(exc).__name__}: {exc}")
            return 2
        rows.append(row)
        source_counts = Counter(row["retrieved_sources"])
        print(
            f"[{index}/{len(questions)}] {item['id']} done "
            f"cost=${row['cost_usd']:.4f} latency={row['latency_ms']}ms "
            f"sources={dict(source_counts)}"
        )

    metric_rows, evaluator = _try_ragas(rows)
    metrics = _mean_metrics(metric_rows)
    thresholds_passed = all(metrics[name] >= threshold for name, threshold in THRESHOLDS.items())

    out_dir = Path("eval/results") / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    total_latency_seconds = time.perf_counter() - started
    total_cost = sum(row["cost_usd"] for row in rows)
    scores = {
        "tag": tag,
        "timestamp": timestamp,
        "n_questions": len(rows),
        "evaluator": evaluator,
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "thresholds_passed": thresholds_passed,
        "total_cost_usd": total_cost,
        "total_latency_seconds": total_latency_seconds,
    }
    (out_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    (out_dir / "config_snapshot.json").write_text(
        json.dumps(_settings_snapshot(), indent=2),
        encoding="utf-8",
    )
    _write_details(out_dir / "details.csv", rows, metric_rows)

    print("\nScores:")
    for metric in METRICS:
        status = "PASS" if metrics[metric] >= THRESHOLDS[metric] else "FAIL"
        print(f"  {metric}: {metrics[metric]:.3f} ({status}, threshold={THRESHOLDS[metric]:.2f})")
    print(f"Evaluator: {evaluator}")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Results: {out_dir}")
    _print_previous_delta(Path("eval/results"), tag, metrics)
    return 0 if thresholds_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="结果标签,如 'baseline'")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_eval(args.tag, args.api)))
