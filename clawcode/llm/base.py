"""Base LLM Provider abstraction.

This module defines the abstract base class for all LLM providers,
including event types, responses, and the provider interface.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Mapping,
)

from pydantic import BaseModel

from .tool_call_normalize import normalize_tool_input_dict


class ProviderEventType(str, Enum):
    """Event types for streaming responses."""

    CONTENT_START = "content_start"
    CONTENT_DELTA = "content_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_USE_START = "tool_use_start"
    TOOL_USE_STOP = "tool_use_stop"
    COMPLETE = "complete"
    ERROR = "error"
    WARNING = "warning"


@dataclass
class TokenUsage:
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Get total token usage."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    input: str | dict[str, Any]
    finished: bool = False

    def get_input_dict(self) -> dict[str, Any]:
        """Get input as dictionary."""
        if isinstance(self.input, dict):
            return normalize_tool_input_dict(self.input, tool_name=self.name)
        try:
            parsed: Any = json.loads(self.input)
        except (json.JSONDecodeError, TypeError):
            return {"raw": self.input}
        if isinstance(parsed, dict):
            return normalize_tool_input_dict(parsed, tool_name=self.name)
        return parsed


@dataclass
class ProviderEvent:
    """Event from streaming LLM response.

    Attributes:
        type: The event type
        content: Text content delta
        thinking: Reasoning/thinking content delta
        tool_call: Tool call information (for TOOL_USE_START)
        response: Complete response (for COMPLETE event)
        error: Exception (for ERROR event)
    """

    type: ProviderEventType
    content: str = ""
    thinking: str = ""
    tool_call: ToolCall | None = None
    response: "ProviderResponse | None" = None
    error: Exception | None = None

    @classmethod
    def content_delta(cls, content: str) -> "ProviderEvent":
        """Create a content delta event."""
        return cls(type=ProviderEventType.CONTENT_DELTA, content=content)

    @classmethod
    def thinking_delta(cls, thinking: str) -> "ProviderEvent":
        """Create a thinking delta event."""
        return cls(type=ProviderEventType.THINKING_DELTA, thinking=thinking)

    @classmethod
    def tool_use_start(cls, tool_call: ToolCall) -> "ProviderEvent":
        """Create a tool use start event."""
        return cls(type=ProviderEventType.TOOL_USE_START, tool_call=tool_call)

    @classmethod
    def tool_use_stop(cls) -> "ProviderEvent":
        """Create a tool use stop event."""
        return cls(type=ProviderEventType.TOOL_USE_STOP)

    @classmethod
    def complete(cls, response: "ProviderResponse") -> "ProviderEvent":
        """Create a complete event."""
        return cls(type=ProviderEventType.COMPLETE, response=response)

    @classmethod
    def error(cls, error: Exception) -> "ProviderEvent":
        """Create an error event."""
        return cls(type=ProviderEventType.ERROR, error=error)


@dataclass
class CacheStats:
    """Cache statistics for prompt caching.

    Attributes:
        cache_read_tokens: Number of tokens read from cache
        cache_creation_tokens: Number of tokens used to create cache
        cached: Whether cache was used
    """

    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cached: bool = False

    @property
    def total_cache_tokens(self) -> int:
        """Get total cached tokens."""
        return self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class ProviderResponse:
    """Complete response from LLM.

    Attributes:
        content: The text content
        thinking: The thinking/reasoning content
        tool_calls: List of tool calls
        usage: Token usage information
        finish_reason: Why the response finished
        model: The model that generated the response
        cache_stats: Cache statistics for prompt caching
    """

    content: str
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    finish_reason: str = "stop"
    model: str = ""
    cache_stats: CacheStats | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


class BaseProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM providers (Anthropic, OpenAI, etc.) must implement
    this interface to be compatible with the agent system.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        system_message: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize the provider.

        Args:
            model: The model identifier
            api_key: API key for authentication
            base_url: Custom base URL for API
            max_tokens: Maximum tokens for generation
            system_message: System message to prepend
            **kwargs: Additional provider-specific options
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.system_message = system_message
        self._extra_options = kwargs
        self._retry_max_retries: int = 2
        self._retry_base_delay: float = 1.0
        self._retry_max_delay: float = 30.0

    @abstractmethod
    async def send_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages and get a complete response.

        Args:
            messages: List of message dictionaries
            tools: Optional list of tool definitions

        Returns:
            The complete response

        Raises:
            Exception: If the request fails
        """
        pass

    @abstractmethod
    async def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream response from the LLM.

        Args:
            messages: List of message dictionaries
            tools: Optional list of tool definitions

        Yields:
            ProviderEvent objects as they arrive

        Raises:
            Exception: If the request fails
        """
        pass

    async def health_check(self) -> bool:
        """Check if the provider is accessible.

        Returns:
            True if healthy, False otherwise
        """
        return True

    async def _with_retry(self, coro_factory, *args, **kwargs):
        """Execute an async callable with retry logic for transient errors.

        Args:
            coro_factory: An async callable (typically a method).
            *args: Positional arguments for the callable.
            **kwargs: Keyword arguments for the callable.

        Returns:
            The result of the callable.

        Raises:
            The last exception if all retries are exhausted.
        """
        import logging
        import random

        from .providers.retry import _RETRYABLE_ERRORS

        log = logging.getLogger(__name__)
        max_retries = getattr(self, "_retry_max_retries", 2)
        base_delay = getattr(self, "_retry_base_delay", 1.0)
        max_delay = getattr(self, "_retry_max_delay", 30.0)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await coro_factory(*args, **kwargs)
            except _RETRYABLE_ERRORS as e:
                last_error = e
                if attempt >= max_retries:
                    break
                delay = min(
                    base_delay * (2 ** attempt)
                    + random.uniform(0, 0.5),
                    max_delay,
                )
                log.info(
                    "Provider call failed (%s), retry %d/%d in %.1fs",
                    type(e).__name__,
                    attempt + 1,
                    self._retry_max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
        raise last_error

    async def close(self) -> None:
        """Close the provider and release underlying HTTP connections.

        Subclasses should override this if they hold additional resources.
        """
        client = getattr(self, "_client", None)
        if client is not None:
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "close"):
                coro = client.close()
                if coro is not None:
                    await coro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    @property
    def supports_tools(self) -> bool:
        """Check if provider supports tool calling.

        Returns:
            True if tools are supported
        """
        return True

    @property
    def supports_attachments(self) -> bool:
        """Check if provider supports file attachments.

        Returns:
            True if attachments are supported
        """
        return True

    @property
    def supports_thinking(self) -> bool:
        """Check if provider supports extended thinking.

        Returns:
            True if thinking is supported
        """
        return False

    def get_tool_schema(self, tool_info: dict[str, Any]) -> dict[str, Any]:
        """Convert tool info to provider-specific schema.

        Args:
            tool_info: Tool information dict

        Returns:
            Provider-specific tool schema
        """
        # Default OpenAI-style schema
        return {
            "type": "function",
            "function": {
                "name": tool_info.get("name"),
                "description": tool_info.get("description"),
                "parameters": {
                    "type": "object",
                    "properties": tool_info.get("parameters", {}),
                    "required": tool_info.get("required", []),
                },
            },
        }


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        model: str | None = None,
        original: Exception | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message
            provider: Provider name
            model: Model name
            original: Original exception
        """
        self.provider = provider
        self.model = model
        self.original = original
        super().__init__(message)


class RateLimitError(ProviderError):
    """Raised when rate limit is hit."""

    pass


class ContextLimitError(ProviderError):
    """Raised when context limit is exceeded."""

    pass


class AuthenticationError(ProviderError):
    """Raised when authentication fails."""

    pass


# Streaming utilities


async def aiter_from_iterator(
    iterator: Any,
) -> AsyncIterator[ProviderEvent]:
    """Convert a synchronous iterator to async.

    Args:
        iterator: Synchronous iterator

    Yields:
        Items from the iterator
    """
    loop = asyncio.get_event_loop()
    while True:
        try:
            item = await loop.run_in_executor(None, next, iterator)
            yield item
        except StopIteration:
            break


async def collect_events(
    event_stream: AsyncIterator[ProviderEvent],
) -> list[ProviderEvent]:
    """Collect all events from a stream.

    Args:
        event_stream: The event stream

    Returns:
        List of all events
    """
    events = []
    async for event in event_stream:
        events.append(event)
    return events
