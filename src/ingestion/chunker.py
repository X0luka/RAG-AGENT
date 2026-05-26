"""Chunk LlamaIndex documents into text nodes for ingestion."""

from llama_index.core import Document
from llama_index.core.node_parser import CodeSplitter, MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import TextNode

from src.config import settings


def _heading_path(metadata: dict) -> list[str]:
    if isinstance(metadata.get("heading_path"), list):
        return metadata["heading_path"]
    if isinstance(metadata.get("header_path"), str):
        return [part for part in metadata["header_path"].split("/") if part]
    headers = []
    for key in sorted(k for k in metadata if k.startswith("Header_")):
        value = metadata.get(key)
        if value:
            headers.append(str(value))
    return headers


def _finalize_nodes(nodes: list[TextNode]) -> list[TextNode]:
    finalized = []
    for node in nodes:
        text = node.text.strip()
        if len(text) < 100:
            continue
        node.text = text
        node.metadata = {**node.metadata, "heading_path": _heading_path(node.metadata)}
        node.metadata.pop("header_path", None)
        for key in list(node.metadata):
            if key.startswith("Header_"):
                node.metadata.pop(key)
        node.metadata["chunk_index"] = len(finalized)
        finalized.append(node)
    return finalized


def _chunk_code_fallback(doc: Document) -> list[TextNode]:
    lines = doc.text.splitlines()
    blocks: list[str] = []
    current_block: list[str] = []
    for line in lines:
        starts_block = line.startswith(("def ", "class ", "async def "))
        if starts_block and current_block:
            blocks.append("\n".join(current_block))
            current_block = []
        current_block.append(line)
    if current_block:
        blocks.append("\n".join(current_block))

    chunks: list[TextNode] = []
    current_chunk: list[str] = []
    current_len = 0
    for block in blocks:
        if current_chunk and current_len + len(block) > 1500:
            chunks.append(TextNode(text="\n\n".join(current_chunk), metadata=dict(doc.metadata)))
            current_chunk = []
            current_len = 0
        current_chunk.append(block)
        current_len += len(block)
        if current_len >= settings.chunk_size:
            chunks.append(TextNode(text="\n\n".join(current_chunk), metadata=dict(doc.metadata)))
            current_chunk = []
            current_len = 0
    if current_chunk:
        chunks.append(TextNode(text="\n\n".join(current_chunk), metadata=dict(doc.metadata)))
    return chunks


def _chunk_code(docs: list[Document]) -> list[TextNode]:
    nodes: list[TextNode] = []
    for doc in docs:
        language = str(doc.metadata.get("language", "text"))
        try:
            splitter = CodeSplitter(
                language=language,
                chunk_lines=40,
                chunk_lines_overlap=15,
                max_chars=1500,
            )
            nodes.extend(splitter.get_nodes_from_documents([doc]))
        except ImportError:
            nodes.extend(_chunk_code_fallback(doc))
        except ValueError:
            nodes.extend(_chunk_code_fallback(doc))
    return nodes


def _split_large_node(node: TextNode) -> list[TextNode]:
    if len(node.text) <= settings.chunk_size:
        return [node]
    splitter = SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    split_nodes = splitter.get_nodes_from_documents(
        [Document(text=node.text, metadata=dict(node.metadata))]
    )
    for split_node in split_nodes:
        split_node.metadata = {**node.metadata, **split_node.metadata}
    return split_nodes


def _chunk_markdown(docs: list[Document]) -> list[TextNode]:
    parser = MarkdownNodeParser()
    nodes: list[TextNode] = []
    for node in parser.get_nodes_from_documents(docs):
        nodes.extend(_split_large_node(node))
    return nodes


def chunk_documents(docs: list[Document], source_type: str) -> list[TextNode]:
    """Chunk documents and attach stable ingestion metadata.

    Args:
        docs: LlamaIndex documents loaded from one source.
        source_type: Source type controlling the chunk strategy.

    Returns:
        Text nodes with chunk_index and heading_path metadata.
    """
    non_empty = [doc for doc in docs if len(doc.text.strip()) >= 50]
    if source_type == "code":
        return _finalize_nodes(_chunk_code(non_empty))
    return _finalize_nodes(_chunk_markdown(non_empty))
