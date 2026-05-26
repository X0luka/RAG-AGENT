"""Application configuration loaded from environment variables via pydantic-settings."""

from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ============ LLM Providers ============
    # DeepSeek（低成本路径）
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # OpenRouter（强模型路径）
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_primary_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_site_url: str = "http://localhost"
    openrouter_site_name: str = "RAG Memory Assistant"

    # AIHubMix（embedding 路径，OpenAI 兼容接口）
    aihubmix_api_key: str
    aihubmix_base_url: str = "https://aihubmix.com/v1"
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Cohere（仅用于 rerank）
    cohere_api_key: str
    rerank_model: str = "rerank-v3.5"

    # ============ Infrastructure ============
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"

    # Langfuse（Cloud 默认，可改 host 切自托管）
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str = "https://cloud.langfuse.com"

    # ============ Retrieval Params（锁定值） ============
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
