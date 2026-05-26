"""Tests for the persistent BM25 index."""

from src.retrieval.bm25 import BM25Index


def test_add_and_search(tmp_path) -> None:
    index = BM25Index(tmp_path / "bm25.pkl")
    index.add_documents(
        ["a", "b", "c"],
        ["alpha beta", "deep learning retrieval", "orange pear"],
        ["one.md", "two.md", "three.md"],
    )

    results = index.search("retrieval", top_k=3)

    assert results[0][0] == "b"


def test_remove_by_source(tmp_path) -> None:
    index = BM25Index(tmp_path / "bm25.pkl")
    index.add_documents(
        ["a", "b", "c"],
        ["alpha beta", "deep learning retrieval", "retrieval pear"],
        ["one.md", "two.md", "three.md"],
    )
    index.remove_by_source("two.md")

    results = index.search("learning retrieval", top_k=3)

    assert all(chunk_id != "b" for chunk_id, _score in results)

