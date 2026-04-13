"""Unified retry/backoff strategy for LLM provider API calls."""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_RETRYABLE_ERRORS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

try:
    from openai import RateLimitError as _OpenAIRateLimit
    _RETRYABLE_ERRORS = _RETRYABLE_ERRORS + (_OpenAIRateLimit,)
except ImportError:
    pass

try:
    from anthropic import RateLimitError as _AnthropicRateLimit
    _RETRYABLE_ERRORS = _RETRYABLE_ERRORS + (_AnthropicRateLimit,)
except ImportError:
    pass


def with_provider_retry(
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[[F], F]:
    """Decorator that adds retry logic to async provider methods.

    Retries on connection errors, timeouts, and rate-limit errors.
    Uses exponential backoff with jitter.

    Args:
        max_retries: Maximum number of retry attempts (default 2).
        base_delay: Initial delay between retries in seconds (default 1.0).
        max_delay: Maximum delay between retries in seconds (default 30.0).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except _RETRYABLE_ERRORS as e:
                    last_error = e
                    if attempt >= max_retries:
                        break
                    import random

                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
                    err_name = type(e).__name__
                    logger.info(
                        "Provider call failed (%s), retry %d/%d in %.1fs",
                        err_name,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
            raise last_error  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
