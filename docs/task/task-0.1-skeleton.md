# Task 0.1 — Project Skeleton

**Milestone**: M0
**Depends on**: 无
**预计**: 1-2 小时

## 目标

创建项目目录结构、依赖配置、Docker Compose、`.env` 模板,跑通基础设施。

## 必读文档

- [`../00-conventions.md`](../00-conventions.md)
- [`../01-config.md`](../01-config.md)

## 输出文件清单

### 必须创建

```
.
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── docs/                              # 已存在,不动
├── src/
│   ├── __init__.py
│   ├── config.py                      # 实现 Settings
│   ├── ingestion/__init__.py
│   ├── retrieval/__init__.py
│   ├── generation/__init__.py
│   ├── orchestration/__init__.py
│   ├── memory/__init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/__init__.py
│   └── observability/__init__.py
├── ui/__init__.py                     # 占位
├── eval/
│   ├── results/.gitkeep
│   └── golden_set.json                # 空数组 []
├── data/
│   ├── raw/.gitkeep
│   ├── processed/.gitkeep
│   └── logs/.gitkeep
├── scripts/                           # 暂留空
└── tests/
    └── __init__.py
```

## 文件内容规约

### `pyproject.toml`

```toml
[project]
name = "ai-learning-companion"
version = "0.1.0"
description = "Local-first RAG and memory assistant"
requires-python = ">=3.11"
dependencies = [
    # LLM SDKs
    "openai>=1.50",
    "cohere>=5.10",
    
    # RAG framework
    "llama-index>=0.13",
    "llama-index-readers-file>=0.4",  # PDFReader 等
    "langgraph>=0.2",
    
    # Vector DB
    "qdrant-client>=1.13",
    
    # Keyword search
    "rank-bm25>=0.2",
    
    # Web
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    
    # Database
    "sqlalchemy>=2.0",
    "aiosqlite>=0.20",
    
    # UI
    "streamlit>=1.40",
    
    # Evaluation
    "ragas>=0.2",
    
    # Observability
    "langfuse>=2.50",
    "loguru>=0.7",
    
    # Config
    "pydantic-settings>=2.5",
    "pydantic>=2.9",
    
    # Utils
    "trafilatura>=1.12",        # HTML extraction
    "python-multipart>=0.0.9",  # FastAPI form 用
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
    "mypy>=1.11",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### `docker-compose.yml`

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: rag_memory_qdrant
    ports:
      - "6333:6333"   # REST
      - "6334:6334"   # gRPC
    volumes:
      - qdrant_storage:/qdrant/storage
    restart: unless-stopped

volumes:
  qdrant_storage:
```

注意:第一阶段 Langfuse 用 Cloud,不在 compose 里。
若以后切自托管,再加 Langfuse 服务。

### `.env.example`

按 `../01-config.md` 中"环境变量清单"一节完整复制。

### `.gitignore`

按 `../00-conventions.md` 第 4.3 节复制。

### `README.md`

```markdown
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
```

### `src/config.py`

完整按 [`../01-config.md`](../01-config.md) 第 "Settings 实现规约" 节实现。

### 各 `__init__.py`

模块占位,内容仅:

```python
"""<模块名> module."""
```

`eval/golden_set.json`:

```json
[]
```

## Verify

执行以下命令,**全部必须通过**:

```bash
# 1. uv 装依赖
uv sync
# 期望:无错误,所有依赖装上

# 2. 启 Qdrant
docker compose up -d
sleep 5
curl -sf http://localhost:6333/ | head -5
# 期望:返回 JSON,状态 200

# 3. 配置可加载
uv run python -c "from src.config import settings; print(settings.qdrant_url)"
# 期望:输出 http://localhost:6333

# 4. 关键依赖能 import
uv run python -c "from openai import AsyncOpenAI; from qdrant_client import AsyncQdrantClient; from langfuse import Langfuse; print('imports ok')"
# 期望:输出 imports ok

# 5. 目录结构完整
ls src/ingestion/ src/retrieval/ src/generation/ src/memory/ src/api/routes/ src/observability/
# 期望:所有目录存在,均含 __init__.py
```

## Notes for Implementation

- 这一步**不要写任何业务代码**,只创建文件和配置
- 使用方必须先在 `.env` 中填入真实 key,否则 `Settings` 实例化会失败
- 若 `Settings` 实例化失败但配置就是没填,在 Task 0.1 阶段允许跳过 verify 第 3 步,
  改为运行 `uv run python -c "from pydantic_settings import BaseSettings; print('ok')"`,
  并在报告中标注"已生成 config.py 但未实际加载(等用户填 key)"。

## 完成后

报告并等待用户:
1. 填好 `.env`
2. 验证 verify 通过
3. 决定是否进入 Task 0.2

---

*Related Tasks: [task-0.2-llm-smoke.md](task-0.2-llm-smoke.md)*
