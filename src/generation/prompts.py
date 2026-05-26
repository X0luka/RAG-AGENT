"""Prompt construction and citation parsing for grounded generation."""

import re
from dataclasses import dataclass

from src.memory.models import Interaction
from src.retrieval import SearchResult

SYSTEM_PROMPT = """You are an AI engineering learning assistant. The user is studying AI engineering and asks questions based on materials they have provided.

Rules:
1. Answer ONLY based on the provided sources below. If the sources don't contain the answer, respond exactly: "I don't have enough information in my knowledge base to answer this. Consider adding more materials."
2. Cite sources by including [source_N] immediately after each factual claim, where N is the source id from the sources block.
3. Be concise. Use code blocks with language tags for code. Use $...$ for inline math, $$...$$ for display math.
4. If the question is ambiguous, ask for clarification before answering.
5. Never invent source IDs. Only use IDs from the provided sources.
6. If conversation history is provided, you may reference it for context, but ground your factual claims in the sources.
"""

USER_PROMPT_TEMPLATE = """{history_section}Sources:
{sources_section}

User question:
{query}"""


@dataclass
class Citation:
    """Citation extracted from a generated answer."""

    source_id: int
    source: str
    page: int | None
    text_preview: str


def format_history_section(history: list[Interaction]) -> str:
    """Format recent conversation history for the prompt.

    Args:
        history: Recent completed interactions.

    Returns:
        Empty string if no history, otherwise a history block ending with two newlines.
    """
    if not history:
        return ""
    lines = ["Recent conversation:"]
    for index, item in enumerate(history, start=1):
        answer = item.answer[:500]
        lines.append(f"[{index}] User: {item.query}")
        lines.append(f"    Assistant: {answer}")
    return "\n".join(lines) + "\n\n"


def format_sources_section(chunks: list[SearchResult]) -> str:
    """Format retrieved chunks as source XML-like blocks.

    Args:
        chunks: Retrieved source chunks.

    Returns:
        Sources block for the user prompt.
    """
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        source = chunk.payload.get("source", "unknown")
        page = chunk.payload.get("page")
        page_value = page if page is not None else "N/A"
        blocks.append(
            f'<source id="{index}" file="{source}" page="{page_value}">\n'
            f"{chunk.text}\n"
            "</source>"
        )
    return "\n".join(blocks)


def parse_citations(answer: str, chunks: list[SearchResult]) -> list[Citation]:
    """Extract source citations from an answer.

    Args:
        answer: Generated answer text.
        chunks: Source chunks provided to the model.

    Returns:
        Deduplicated citations in first-appearance order.
    """
    citations: list[Citation] = []
    seen: set[int] = set()
    for match in re.finditer(r"\[(?:source_)?(\d+)\]", answer):
        source_id = int(match.group(1))
        if source_id in seen or source_id < 1 or source_id > len(chunks):
            continue
        seen.add(source_id)
        chunk = chunks[source_id - 1]
        citations.append(
            Citation(
                source_id=source_id,
                source=str(chunk.payload.get("source", "")),
                page=chunk.payload.get("page"),
                text_preview=chunk.text[:200],
            )
        )
    return citations
