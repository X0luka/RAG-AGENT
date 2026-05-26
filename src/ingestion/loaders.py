"""Load source files into LlamaIndex documents with normalized metadata."""

from html.parser import HTMLParser
from pathlib import Path

import trafilatura
from llama_index.core import Document
from llama_index.readers.file import PDFReader

from src.api.errors import UnsupportedFileTypeError
from src.config import settings

CODE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
}


class _TextHTMLParser(HTMLParser):
    """Small HTML text extractor used when trafilatura cannot extract content."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        """Collect non-empty text fragments from HTML data nodes."""
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        """Return extracted text joined by newlines."""
        return "\n".join(self._parts)


def _source_for(path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.raw_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _with_metadata(doc: Document, path: Path, source_type: str) -> Document:
    doc.metadata = {
        **doc.metadata,
        "source": _source_for(path),
        "source_type": source_type,
    }
    return doc


def load_pdf(path: Path) -> list[Document]:
    """Load a PDF with one document per page.

    Args:
        path: PDF file path.

    Returns:
        Documents with page metadata.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    documents = PDFReader().load_data(path)
    for index, doc in enumerate(documents, start=1):
        doc.metadata = {**doc.metadata, "page": index}
    return documents


def load_markdown(path: Path) -> list[Document]:
    """Load a markdown or text file as one document.

    Args:
        path: Markdown/text file path.

    Returns:
        Single document containing the full file text.
    """
    return [Document(text=path.read_text(encoding="utf-8"), metadata={"page": None})]


def load_code(path: Path) -> list[Document]:
    """Load a source code file as one document.

    Args:
        path: Code file path.

    Returns:
        Single document with language metadata.
    """
    language = CODE_LANGUAGES.get(path.suffix.lower(), "text")
    return [
        Document(
            text=path.read_text(encoding="utf-8"),
            metadata={"language": language, "page": None},
        )
    ]


def load_html(path: Path) -> list[Document]:
    """Extract readable text from an HTML document.

    Args:
        path: HTML file path.

    Returns:
        Single document containing extracted text.
    """
    html = path.read_text(encoding="utf-8")
    text = trafilatura.extract(html)
    if not text:
        parser = _TextHTMLParser()
        parser.feed(html)
        text = parser.text()
    return [Document(text=text or "", metadata={"page": None})]


def auto_load(path: Path, source_type: str) -> list[Document]:
    """Dispatch to a loader by file extension and normalize metadata.

    Args:
        path: Source file path.
        source_type: One of paper, code, article, or transcript.

    Returns:
        Loaded documents with source and source_type metadata.

    Raises:
        UnsupportedFileTypeError: If the extension is not supported.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = load_pdf(path)
    elif suffix in {".md", ".markdown", ".txt"}:
        docs = load_markdown(path)
    elif suffix in CODE_LANGUAGES:
        docs = load_code(path)
    elif suffix in {".html", ".htm"}:
        docs = load_html(path)
    else:
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix}")
    return [_with_metadata(doc, path, source_type) for doc in docs]

