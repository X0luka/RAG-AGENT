# 01 — Configuration

## 文件位置

- 实现:`src/config.py`
- 模板:`.env.example`(进 git)
- 实际:`.env`(不进 git)

## Settings 实现规约

使用 `pydantic-settings`,实现为单例。

```python
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============ LLM Providers ============
    # DeepSeek(低成本路径)
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    
    # OpenRouter(强模型路径)
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_primary_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_site_url: str = "http://localhost"
    openrouter_site_name: str = "RAG Memory Assistant"
    
    # AIHubMix(embedding 路径,OpenAI 兼容接口)
    aihubmix_api_key: str
    aihubmix_base_url: str = "https://aihubmix.com/v1"
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_dim: int = 1536
    
    # Cohere(仅用于 rerank)
    cohere_api_key: str
    rerank_model: str = "rerank-v3.5"
    
    # ============ Infrastructure ============
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"
    
    # Langfuse(Cloud 默认,可改 host 切自托管)
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str = "https://cloud.langfuse.com"
    
    # ============ Retrieval Params(锁定值) ============
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k_vector: int = 30
    top_k_bm25: int = 30
    top_k_rerank: int = 8
    rrf_k: int = 60
    
    # ============ Self-RAG Params ============
    self_rag_min_retrieval_score: float = 3.5
    self_rag_max_rewrites: int = 2
    
    # ============ Generation Params ============
    max_tokens_response: int = 2048
    temperature: float = 0.3
    request_timeout_seconds: int = 60
    
    # ============ Paths ============
    data_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw")
    db_path: Path = Path("data/memory.db")
    bm25_index_path: Path = Path("data/processed/bm25.pkl")
    log_path: Path = Path("data/logs/app.log")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
```

## 环境变量清单(`.env.example`)

```bash
# === LLM Providers ===
# DeepSeek: https://platform.deepseek.com/api_keys
DEEPSEEK_API_KEY=sk-...

# OpenRouter: https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-v1-...
# 可选:覆盖默认模型
# OPENROUTER_PRIMARY_MODEL=anthropic/claude-sonnet-4.6

# AIHubMix embedding(OpenAI 兼容): https://aihubmix.com/
AIHUBMIX_API_KEY=sk-...
AIHUBMIX_BASE_URL=https://aihubmix.com/v1
# 可选:覆盖默认 embedding 模型
# EMBEDDING_MODEL=text-embedding-3-small

# Cohere: https://dashboard.cohere.com/api-keys
COHERE_API_KEY=...

# === Infrastructure ===
# Qdrant(本地 Docker)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=documents

# Langfuse(默认 Cloud)
# 注册 https://cloud.langfuse.com 后在项目设置创建 API Keys
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

## Embedding Client 规约

Embedding 仍用 OpenAI SDK,但 client 必须使用 AIHubMix key 和 base URL:

```python
from openai import AsyncOpenAI

embedding_client = AsyncOpenAI(
    api_key=settings.aihubmix_api_key,
    base_url=settings.aihubmix_base_url,
)
```

`embed_text` 和 `embed_batch` 都从 `settings.embedding_model` 读取模型名,不得硬编码 provider 或 key。

## 访问规则

```python
# 正确
from src.config import settings
url = settings.qdrant_url

# 禁止
import os
url = os.environ["QDRANT_URL"]
```

## 配置变更流程

1. 修改本文档,描述新字段或调整
2. 修改 `src/config.py` 实现
3. 修改 `.env.example` 模板
4. 在 `log/spec.log.md` 记录变更
5. 受影响的 Task 文档更新

---

*Related: [00-conventions.md](00-conventions.md), [05-generation.md](05-generation.md), [08-observability.md](08-observability.md)*
