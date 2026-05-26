"""Persistent BM25 keyword index used by ingestion and retrieval."""

import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi

from src.config import settings


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class BM25Index:
    """BM25 index with pickle persistence."""

    def __init__(self, path: Path) -> None:
        """Create an index stored at path.

        Args:
            path: Pickle file path.
        """
        self.path = path
        self.chunk_ids: list[str] = []
        self.sources: list[str] = []
        self.documents: list[list[str]] = []
        self.raw_texts: list[str] = []
        self._bm25: BM25Okapi | None = None

    def _rebuild(self) -> None:
        self._bm25 = BM25Okapi(self.documents) if self.documents else None

    def add_documents(self, chunk_ids: list[str], texts: list[str], sources: list[str]) -> None:
        """Append documents to the index.

        Args:
            chunk_ids: Qdrant point ids.
            texts: Raw chunk texts.
            sources: Source path for each chunk.

        Raises:
            ValueError: If list lengths do not match.
        """
        if not (len(chunk_ids) == len(texts) == len(sources)):
            raise ValueError("chunk_ids, texts, and sources must have the same length")
        self.chunk_ids.extend(chunk_ids)
        self.sources.extend(sources)
        self.raw_texts.extend(texts)
        self.documents.extend(_tokenize(text) for text in texts)
        self._rebuild()

    def remove_by_source(self, source: str) -> None:
        """Remove all chunks for a source.

        Args:
            source: Source path to remove.
        """
        kept = [
            (chunk_id, item_source, document, raw_text)
            for chunk_id, item_source, document, raw_text in zip(
                self.chunk_ids,
                self.sources,
                self.documents,
                self.raw_texts,
                strict=True,
            )
            if item_source != source
        ]
        self.chunk_ids = [item[0] for item in kept]
        self.sources = [item[1] for item in kept]
        self.documents = [item[2] for item in kept]
        self.raw_texts = [item[3] for item in kept]
        self._rebuild()

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Search the index.

        Args:
            query: Keyword query.
            top_k: Maximum result count.

        Returns:
            Tuples of chunk id and BM25 score sorted descending.
        """
        if not self._bm25 or not query.strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(
            zip(self.chunk_ids, scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        return [(chunk_id, float(score)) for chunk_id, score in ranked[:top_k] if score > 0]

    def save(self) -> None:
        """Persist the index to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chunk_ids": self.chunk_ids,
            "sources": self.sources,
            "documents": self.documents,
            "raw_texts": self.raw_texts,
        }
        with self.path.open("wb") as file:
            pickle.dump(payload, file)

    def load(self) -> None:
        """Load the index from disk, or initialize empty if absent."""
        if not self.path.exists():
            self.chunk_ids = []
            self.sources = []
            self.documents = []
            self.raw_texts = []
            self._bm25 = None
            return
        with self.path.open("rb") as file:
            payload = pickle.load(file)
        self.chunk_ids = payload.get("chunk_ids", [])
        self.sources = payload.get("sources", [])
        self.documents = payload.get("documents", [])
        self.raw_texts = payload.get("raw_texts", [])
        self._rebuild()


bm25_index = BM25Index(settings.bm25_index_path)

