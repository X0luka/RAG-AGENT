# RAG Memory Assistant

A local-first knowledge-base Q&A assistant that helps you ask questions over your own
documents, get grounded answers with citations, and keep a lightweight history of previous
interactions.

## What It Does

RAG Memory Assistant lets you build a private knowledge base from local materials such as
papers, articles, code files, and notes. After ingestion, you can ask questions through a web
UI or API, and the assistant answers using retrieved source chunks instead of relying only on
model memory.

Core capabilities:

- Ingest local documents into a searchable knowledge base
- Retrieve relevant context with hybrid search and reranking
- Generate grounded answers with source citations
- Keep basic interaction history and feedback
- Use either a Streamlit web UI or FastAPI endpoints
- Run offline evaluation to measure answer quality

## How It Works

```text
Documents
  -> parsing and chunking
  -> embeddings + vector storage
  -> BM25 keyword index
  -> hybrid retrieval
  -> reranking
  -> prompt assembly
  -> LLM answer with citations
  -> interaction history
```

The system combines vector search, keyword search, and reranking before sending retrieved
sources to the language model. Answers are expected to cite the provided source chunks.

## Architecture

```text
Streamlit UI
  -> FastAPI API
    -> Ingestion pipeline
    -> Retrieval pipeline
    -> Generation pipeline
    -> Memory/history store

Storage:
  - Qdrant for vector search
  - BM25 index for keyword search
  - SQLite for document metadata and interaction history
```

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| API | FastAPI + Uvicorn |
| Package manager | uv |
| Vector database | Qdrant |
| Keyword search | rank-bm25 |
| Embeddings | AIHubMix OpenAI-compatible API |
| Reranking | Cohere rerank |
| LLM providers | DeepSeek and OpenRouter |
| Memory store | SQLite + SQLAlchemy async |
| Observability | Langfuse + loguru |
| Evaluation | RAGAS |
| Runtime | Docker Compose |

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
```

Fill in the required API keys in `.env`.

### 2. Run With Docker

```bash
docker compose up --build
```

Open:

- Web UI: http://localhost:8501
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### 3. Local Development Mode

If you are editing prompts or backend code, run Qdrant in Docker and run the app locally:

```bash
docker compose up -d qdrant
uv sync
uv run uvicorn src.api.main:app --reload --port 8000
```

In another terminal:

```bash
uv run streamlit run ui/app.py
```

Then open:

```text
http://localhost:8501
```

## Using The App

### Ingest Documents

Use the `Documents` page in the web UI to upload and ingest files.

You can also ingest from the command line:

```bash
uv run python scripts/ingest_one.py data/raw/example.pdf --type paper
```

### Ask Questions

Use the `Chat` page in the web UI, or run:

```bash
uv run python scripts/ask.py "What is self-attention?"
```

Answers include citations when the model references retrieved sources.

### Review History

Use the `History` page to inspect previous questions, answers, citations, feedback, and costs.

## Evaluation

Evaluation is an offline workflow and is not included in the runtime Docker image by default.

Install evaluation dependencies:

```bash
uv sync --extra eval
```

Run an evaluation:

```bash
uv run --extra eval python eval/run_eval.py --tag baseline
```

Results are written to:

```text
eval/results/<tag>/
```

See `docs/09-eval.md` for details.

## Current Status

RAG Memory Assistant currently supports a working local-first RAG workflow: document ingestion,
hybrid retrieval, reranking, grounded answer generation, source citations, basic interaction
history, a web UI, an API, and offline evaluation.

Future versions may explore more advanced memory and learning-assistant capabilities:

- Fine-grained user profiles and long-term memory
- Extracting durable facts from conversations
- Abstracting concepts across documents and interactions
- Tracking learning progress and concept mastery
- Recommending reviews or follow-up materials
- Handling memory conflicts, updates, and decay
- Improving retrieval through Self-RAG query rewriting
- Expanding observability across retrieval, generation, and memory

## Documentation

Detailed design docs live in `docs/`:

- `docs/03-ingestion.md` - ingestion pipeline
- `docs/04-retrieval.md` - retrieval and reranking
- `docs/05-generation.md` - prompt and generation design
- `docs/06-memory.md` - interaction history and memory
- `docs/07-api.md` - API design
- `docs/08-observability.md` - Langfuse and logging
- `docs/09-eval.md` - evaluation workflow

Implementation task notes live in `docs/task/`.

## License

TBD
