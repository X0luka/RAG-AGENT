"""Compatibility wrappers for Langfuse decorators."""

import os
from collections.abc import Callable
from typing import TypeVar

from src.config import settings

os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)

from langfuse import observe as _observe

F = TypeVar("F", bound=Callable)


def observe(name: str) -> Callable[[F], F]:
    """Return a Langfuse observe decorator.

    Args:
        name: Span name.

    Returns:
        Decorator compatible with the installed Langfuse SDK.
    """
    return _observe(name=name)
