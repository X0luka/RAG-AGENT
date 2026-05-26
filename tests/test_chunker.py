"""Tests for document chunking behavior."""

from llama_index.core import Document

from src.ingestion.chunker import chunk_documents


def test_chunk_markdown_respects_headings() -> None:
    text = (
        "# Root\n\n"
        + "Intro sentence for root. " * 12
        + "\n\n## Child\n\n"
        + "Child section details. " * 12
    )
    nodes = chunk_documents(
        [Document(text=text, metadata={"source": "note.md", "source_type": "article"})],
        "article",
    )

    assert nodes
    assert any(node.metadata["heading_path"] == ["Root"] for node in nodes)


def test_chunk_code_uses_code_splitter() -> None:
    text = (
        "def alpha():\n"
        "    value = 1\n"
        "    return value\n\n"
        "def beta():\n"
        "    value = 2\n"
        "    return value\n"
    ) * 8
    nodes = chunk_documents(
        [
            Document(
                text=text,
                metadata={"source": "code.py", "source_type": "code", "language": "python"},
            )
        ],
        "code",
    )

    assert nodes
    assert all("return value" in node.text for node in nodes)


def test_chunk_index_increments() -> None:
    text = "\n\n".join(f"## Section {index}\n\n" + "Body text. " * 20 for index in range(4))
    nodes = chunk_documents(
        [Document(text=text, metadata={"source": "note.md", "source_type": "article"})],
        "article",
    )

    assert [node.metadata["chunk_index"] for node in nodes] == list(range(len(nodes)))

