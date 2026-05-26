"""LLM provider clients and streaming/non-streaming generation helpers."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from langfuse.openai import AsyncOpenAI
from loguru import logger
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from src.config import settings
from src.observability.decorators import ensure_langfuse_env

ensure_langfuse_env()

_deepseek_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=settings.request_timeout_seconds,
)

_openrouter_client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url=settings.openrouter_base_url,
    timeout=settings.request_timeout_seconds,
    default_headers={
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_site_name,
    },
)


@dataclass
class LLMUsage:
    """Token and cost usage for one LLM call."""

    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    model: str
    provider: str


@dataclass
class LLMResult:
    """Non-streaming LLM result."""

    content: str
    usage: LLMUsage


@dataclass
class LLMChunk:
    """Streaming LLM chunk."""

    delta: str
    done: bool
    usage: LLMUsage | None


ProviderKind = Literal["cheap", "strong"]

PRICING_USD_PER_M = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "anthropic/claude-sonnet-4.6": {"input": 3.00, "output": 15.00},
    "anthropic/claude-haiku-4.5": {"input": 1.00, "output": 5.00},
    "openai/gpt-5": {"input": 5.00, "output": 20.00},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 5.00},
}


class LLMError(Exception):
    """Raised when an LLM provider call fails."""


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from static per-million token pricing."""
    pricing = PRICING_USD_PER_M.get(model)
    if pricing is None:
        logger.warning("No pricing configured for model {model}", model=model)
        return 0.0
    return (
        prompt_tokens * pricing["input"] / 1_000_000
        + completion_tokens * pricing["output"] / 1_000_000
    )


def _get_client_and_model(kind: ProviderKind) -> tuple[AsyncOpenAI, str, str]:
    if kind == "cheap":
        return _deepseek_client, settings.deepseek_model, "deepseek"
    return _openrouter_client, settings.openrouter_primary_model, "openrouter"


def _usage_from_response(
    usage,
    model: str,
    provider: str,
) -> LLMUsage:
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=calculate_cost(model, prompt_tokens, completion_tokens),
        model=model,
        provider=provider,
    )


async def _sleep_for_retry(attempt: int) -> None:
    await asyncio.sleep(2 ** (attempt - 1))


async def call_llm(system: str, user: str, kind: ProviderKind = "strong") -> LLMResult:
    """Call an LLM provider without streaming."""
    client, model, provider = _get_client_and_model(kind)
    for attempt in range(1, 4):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=settings.temperature,
                max_tokens=settings.max_tokens_response,
            )
            content = response.choices[0].message.content or ""
            usage = _usage_from_response(response.usage, model, provider)
            return LLMResult(content=content, usage=usage)
        except RateLimitError as exc:
            if attempt == 3:
                raise LLMError(str(exc)) from exc
            await _sleep_for_retry(attempt)
        except (APIConnectionError, APITimeoutError) as exc:
            if attempt == 2:
                raise LLMError(str(exc)) from exc
            await _sleep_for_retry(attempt)
        except APIStatusError as exc:
            if exc.status_code >= 500 and attempt < 2:
                await _sleep_for_retry(attempt)
                continue
            raise LLMError(str(exc)) from exc
    raise LLMError("LLM call failed after retries")


async def stream_llm(
    system: str,
    user: str,
    kind: ProviderKind = "strong",
) -> AsyncIterator[LLMChunk]:
    """Stream an LLM provider response."""
    client, model, provider = _get_client_and_model(kind)
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=settings.temperature,
            max_tokens=settings.max_tokens_response,
            stream=True,
            stream_options={"include_usage": True},
        )
        final_usage = None
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield LLMChunk(delta=chunk.choices[0].delta.content, done=False, usage=None)
            if chunk.usage:
                final_usage = _usage_from_response(chunk.usage, model, provider)
        yield LLMChunk(delta="", done=True, usage=final_usage)
    except (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
        raise LLMError(str(exc)) from exc
