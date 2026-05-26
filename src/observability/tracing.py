"""Langfuse observability client singleton."""

from langfuse import Langfuse
from src.config import settings

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    """获取 Langfuse 客户端单例。

    Returns:
        初始化后的 Langfuse 实例。
    """
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


def shutdown_langfuse() -> None:
    """flush 所有 pending trace 数据，在应用关闭时调用。"""
    if _langfuse:
        _langfuse.flush()
