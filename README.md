# RAG Memory Assistant

Local-first RAG + Memory assistant for private knowledge-base Q&A.

See root documentation files and `docs/` for project documentation.

## Setup

```bash
# 1. 复制环境变量
cp .env.example .env
# 编辑 .env 填入 API keys

# 2. 装依赖
uv sync

# 3. 启动 Qdrant
docker compose up -d

# 4. 验证连通
python scripts/test_llm.py
```

## Run

```bash
# CLI
python scripts/ask.py "what is attention"

# API
uvicorn src.api.main:app --reload

# UI
streamlit run ui/app.py
```

## Docker

```bash
docker compose up --build
```

- UI: http://localhost:8501
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Docker image excludes offline evaluation dependencies such as RAGAS.

## Evaluation

```bash
uv sync --extra eval
uv run --extra eval python eval/run_eval.py --help
```
