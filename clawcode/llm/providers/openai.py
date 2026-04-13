"""OpenAI provider for ClawCode.

This module provides integration with OpenAI's GPT models and O series reasoning models.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncIterator, Literal

from openai import AsyncOpenAI

from ..openai_compat.adapter import AdapterContext, NullAdapter, select_openai_compat_adapter
from ..base import (
    BaseProvider,
    CacheStats,
    ProviderEvent,
    ProviderEventType,
    ProviderResponse,
    ToolCall,
    TokenUsage,
)


# O series models that support reasoning
REASONING_MODELS = {
    "o1",
    "o1-preview",
    "o1-mini",
    "o1-pro",
    "o3",
    "o3-mini",
    "o4-mini",
}

# Models that support reasoning_effort parameter
REASONING_EFFORT_MODELS = {
    "o1",
    "o1-pro",
    "o3",
    "o3-mini",
    "o4-mini",
}

# Models that do NOT support streaming
NON_STREAMING_MODELS = {
    "o1",
    "o1-preview",
    "o1-mini",
    "o1-pro",
}

# Models that support function calling
FUNCTION_CALLING_MODELS = {
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4-turbo-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    # O series models that support function calling
    "o3",
    "o3-mini",
    "o4-mini",
}

# Models known to NOT support function calling.
# Any model NOT in this set (including OpenAI-compatible models accessed
# via custom base_url, e.g. glm-5, deepseek, qwen, etc.) will have tools
# passed through to the API by default.
NO_FUNCTION_CALLING_MODELS = {
    "o1",
    "o1-preview",
    "o1-mini",
    "o1-pro",
}

_TOOL_ECHO_START_RE = re.compile(r"^\s*(?:\{|\[|```json)", re.IGNORECASE)


class OpenAIProvider(BaseProvider):
    """OpenAI GPT and O series reasoning provider.

    Supports GPT-4, GPT-4 Turbo, GPT-4o, GPT-3.5 Turbo, and O series reasoning models.
    Also supports automatic prompt caching for eligible models.
    """

    # Models that support function calling
    FUNCTION_CALLING_MODELS = FUNCTION_CALLING_MODELS

    # Models that support reasoning_effort parameter
    REASONING_EFFORT_MODELS = REASONING_EFFORT_MODELS

    # Models that do NOT support streaming
    NON_STREAMING_MODELS = NON_STREAMING_MODELS

    # Models that support automatic prompt caching
    CACHING_SUPPORTED_MODELS = {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "o1",
        "o1-preview",
        "o1-mini",
        "o3",
        "o3-mini",
        "o4-mini",
    }

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        reasoning_effort: Literal["low", "medium", "high"] = "medium",
        caching_enabled: bool = True,
        timeout: float | int | None = None,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            model: Model identifier
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            base_url: Custom base URL (for Azure or other compatible APIs)
            max_tokens: Maximum tokens in response
            reasoning_effort: Reasoning effort level for O series models (low/medium/high)
            caching_enabled: Enable prompt caching (default: True)
            timeout: Optional HTTP client timeout in seconds (passed to AsyncOpenAI).
        """
        self._model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._caching_enabled = caching_enabled
        self._base_url = base_url
        self._compat_adapter = select_openai_compat_adapter(
            AdapterContext(model=model, base_url=base_url)
        )

        # Prefer explicit api_key (typically from Settings.providers[...]),
        # fallback to environment variable for convenience.
        if api_key is None:
            api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY environment variable or "
                "provide api_key/base_url via providers configuration."
            )

        # Initialize client (supports custom base_url for OpenAI-compatible APIs).
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if timeout is not None:
            client_kwargs["timeout"] = float(timeout)

        self._client = AsyncOpenAI(**client_kwargs)

    @property
    def openai_compat_adapter(self) -> Any:
        """Selected OpenAI-compatible adapter (or NullAdapter)."""
        return self._get_compat_adapter()

    def _get_compat_adapter(self) -> Any:
        a = getattr(self, "_compat_adapter", None)
        if a is not None:
            return a
        try:
            model = getattr(self, "_model", "")
            base_url = getattr(self, "_base_url", None)
            a = select_openai_compat_adapter(AdapterContext(model=model, base_url=base_url))
        except Exception:
            a = NullAdapter()
        setattr(self, "_compat_adapter", a)
        return a

    def should_inject_reasoning_history(self, *, tools_present: bool) -> bool:
        """Whether the calling layer should return reasoning_content in messages."""
        try:
            return bool(
                self._get_compat_adapter().should_inject_reasoning_history(
                    tools_present=tools_present
                )
            )
        except Exception:
            return False

    @property
    def model(self) -> str:
        """Get the model identifier.

        Returns:
            Model name
        """
        return self._model

    @property
    def supports_streaming(self) -> bool:
        """Check if the current model supports streaming.

        Returns:
            True if streaming is supported
        """
        return self._model not in self.NON_STREAMING_MODELS

    @property
    def supports_reasoning_effort(self) -> bool:
        """Check if the current model supports reasoning_effort parameter.

        Returns:
            True if reasoning_effort is supported
        """
        return self._model in self.REASONING_EFFORT_MODELS

    @property
    def supports_caching(self) -> bool:
        """Check if the current model supports prompt caching.

        Returns:
            True if prompt caching is supported and enabled
        """
        return self._caching_enabled and self._model in self.CACHING_SUPPORTED_MODELS

    def _is_reasoning_model(self) -> bool:
        """Check if current model is a reasoning model.

        Returns:
            True if it's a reasoning model
        """
        return self._model in REASONING_MODELS

    def _build_request_params(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build request parameters for the API call.

        Args:
            messages: Message history
            tools: Available tools for function calling
            stream: Whether to stream the response

        Returns:
            Request parameters dictionary
        """
        tools_present = bool(tools)

        # Convert messages to OpenAI format (handles multimodal content)
        openai_messages = self._convert_messages(messages, tools_present=tools_present)

        request_params: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
        }

        # Add max_tokens for non-reasoning models or models that support it
        # Some reasoning models like o3-mini support max_completion_tokens instead
        if self._is_reasoning_model():
            # For O series models, use max_completion_tokens
            request_params["max_completion_tokens"] = self._max_tokens
        else:
            request_params["max_tokens"] = self._max_tokens

        # Add reasoning_effort for supported models
        if self.supports_reasoning_effort:
            request_params["reasoning_effort"] = self._reasoning_effort

        # Add streaming if supported and requested
        if stream and self.supports_streaming:
            request_params["stream"] = True
            # Include stream_options to get usage information
            request_params["stream_options"] = {"include_usage": True}

        # Add tools if available and model is not known to lack support.
        # This allows OpenAI-compatible models (glm, deepseek, qwen, etc.)
        # accessed via custom base_url to use function calling by default.
        if tools and self._model not in NO_FUNCTION_CALLING_MODELS:
            request_params["tools"] = self._convert_tools(tools)
            request_params["tool_choice"] = "auto"

        # Vendor-specific patching for OpenAI-compatible gateways (DeepSeek, etc.)
        request_params = self._get_compat_adapter().patch_request_params(
            request_params,
            tools_present=tools_present,
            stream=stream,
        )

        return request_params

    async def send_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages and get complete response.

        Args:
            messages: Message history
            tools: Available tools for function calling

        Returns:
            Provider response
        """
        # Prepare request parameters
        request_params = self._build_request_params(messages, tools, stream=False)

        # Make request with retry
        async def _do_call():
            return await self._client.chat.completions.create(**request_params)

        response = await self._with_retry(_do_call)

        # Parse response
        message = response.choices[0].message
        content = message.content or ""

        # Extract reasoning/thinking content (supports OpenAI + compatible vendors).
        thinking = self._extract_thinking(message)

        # Some OpenAI-compatible gateways may leave `content` empty but provide
        # usable assistant text in `reasoning_content`. When `content` is blank,
        # treat non-tool-echo reasoning as the completion body so summarizer
        # (/compact) does not see an empty result.
        if not (content or "").strip():
            rc = (str(thinking or "")).strip()
            if rc and not self._looks_like_tool_echo_chunk(rc):
                content = rc

        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        input=self._parse_arguments(tc.function.arguments),
                    )
                )

        # Get usage with cache information
        cache_read_tokens = 0
        cache_creation_tokens = 0

        if response.usage:
            # OpenAI provides cache information in usage
            cache_read_tokens = getattr(
                response.usage, "prompt_tokens_details", None
            )
            if cache_read_tokens:
                cache_read_tokens = getattr(
                    cache_read_tokens, "cached_tokens", 0
                ) or 0
            else:
                cache_read_tokens = 0

        usage = TokenUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

        # Build cache stats
        cache_stats = CacheStats(
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cached=cache_read_tokens > 0,
        )

        return ProviderResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=response.choices[0].finish_reason or "stop",
            model=self._model,
            cache_stats=cache_stats,
        )

    async def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream response with events.

        For O series models that don't support streaming, this falls back to
        non-streaming mode and yields the complete response.

        Args:
            messages: Message history
            tools: Available tools

        Yields:
            ProviderEvent objects
        """
        # Check if model supports streaming
        if not self.supports_streaming:
            # Fall back to non-streaming for models that don't support it
            response = await self.send_messages(messages, tools)

            # Yield thinking content first if available
            if response.thinking:
                yield ProviderEvent.thinking_delta(response.thinking)

            # Yield content
            if response.content:
                yield ProviderEvent.content_delta(response.content)

            # Yield complete event
            yield ProviderEvent.complete(response)
            return

        # Prepare request parameters for streaming
        request_params = self._build_request_params(messages, tools, stream=True)

        # Stream response with retry on connection init
        async def _start_stream():
            return await self._client.chat.completions.create(**request_params)

        stream = await self._with_retry(_start_stream)

        content_buffer = []
        thinking_buffer = []
        tool_calls_buffer: dict[str, dict] = {}
        _index_to_key: dict[int, str] = {}
        suppress_content_stream = False

        # Track usage from stream
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0

        async for chunk in stream:
            # Check for usage information in the chunk
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0

                # Extract cache information
                prompt_details = getattr(chunk.usage, "prompt_tokens_details", None)
                if prompt_details:
                    cache_read_tokens = getattr(prompt_details, "cached_tokens", 0) or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Content delta
            if delta.content:
                content = delta.content
                content_buffer.append(content)
                if not suppress_content_stream and not self._looks_like_tool_echo_chunk(content):
                    yield ProviderEvent.content_delta(content)

            # Reasoning/thinking content delta (for supported models)
            fallback_thinking = self._extract_thinking(delta)
            if fallback_thinking:
                thinking_buffer.append(fallback_thinking)
                yield ProviderEvent.thinking_delta(fallback_thinking)

            # Tool call deltas: OpenAI (and compatible APIs like glm/deepseek)
            # stream tool calls as a series of chunks keyed by `tc.index`.
            # The first chunk for each index carries `tc.id`; subsequent
            # chunks only carry `tc.index` with `tc.id == None`.  We use a
            # separate mapping from index?key so that later chunks correctly
            # append to the buffer created by the first chunk.
            if delta.tool_calls:
                suppress_content_stream = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx is None:
                        continue

                    # Resolve the stable buffer key for this index
                    if idx in _index_to_key:
                        buf_key = _index_to_key[idx]
                    else:
                        buf_key = tc.id or f"call_{idx}"
                        _index_to_key[idx] = buf_key
                        tool_calls_buffer[buf_key] = {
                            "id": buf_key,
                            "name": "",
                            "arguments_chunks": [],
                        }
                        yield ProviderEvent.tool_use_start(
                            ToolCall(id=buf_key, name="", input={})
                        )

                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[buf_key]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[buf_key]["arguments_chunks"].append(
                                tc.function.arguments
                            )

        # Convert tool calls
        tool_calls = []
        for tc_data in tool_calls_buffer.values():
            if tc_data["name"]:
                arguments = "".join(tc_data["arguments_chunks"])
                try:
                    args = self._parse_arguments(arguments)
                except Exception:
                    args = {}

                tool_calls.append(
                    ToolCall(
                        id=tc_data["id"],
                        name=tc_data["name"],
                        input=args,
                    )
                )

                yield ProviderEvent.tool_use_stop()

        # Build usage with cache information
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

        # Build cache stats
        cache_stats = CacheStats(
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cached=cache_read_tokens > 0,
        )

        # Complete event
        content = "".join(content_buffer)
        if tool_calls and self._should_suppress_final_content(content):
            content = ""
        thinking = "".join(thinking_buffer)
        yield ProviderEvent.complete(
            ProviderResponse(
                content=content,
                thinking=thinking,
                tool_calls=tool_calls,
                usage=usage,
                finish_reason="stop",
                model=self._model,
                cache_stats=cache_stats,
            )
        )

    @staticmethod
    def _looks_like_tool_echo_chunk(chunk: str) -> bool:
        text = (chunk or "").strip()
        if len(text) < 40:
            return False
        if not _TOOL_ECHO_START_RE.match(text):
            return False
        lower = text.lower()
        return (
            '"file_path"' in lower
            or '"tool_call_id"' in lower
            or '"arguments"' in lower
            or '"content"' in lower
        )

    @staticmethod
    def _should_suppress_final_content(content: str) -> bool:
        text = (content or "").strip()
        if not text:
            return False
        if len(text) > 2000:
            return True
        if not _TOOL_ECHO_START_RE.match(text):
            return False
        lower = text.lower()
        return (
            '"file_path"' in lower
            and '"content"' in lower
        ) or (
            '"tool_call_id"' in lower
            and '"arguments"' in lower
        )

    @staticmethod
    def _thinking_from_reasoning_details(details: Any) -> str:
        """Best-effort extraction for vendors returning reasoning_details.

        Supports list/dict/object forms and tolerates heterogeneous entries.
        """
        if details is None:
            return ""
        if isinstance(details, str):
            return details

        chunks: list[str] = []
        items: list[Any]
        if isinstance(details, list):
            items = details
        else:
            items = [details]

        for item in items:
            text = ""
            if isinstance(item, dict):
                val = item.get("text")
                if isinstance(val, str):
                    text = val
            else:
                val = getattr(item, "text", None)
                if isinstance(val, str):
                    text = val
            if text:
                chunks.append(text)

        return "".join(chunks)

    @classmethod
    def _extract_thinking(cls, payload: Any) -> str:
        """Extract thinking text from OpenAI-compatible response payloads."""
        if payload is None:
            return ""

        # OpenAI o-series and many compatible vendors.
        rc = getattr(payload, "reasoning_content", None)
        if isinstance(rc, str) and rc:
            return rc
        if isinstance(payload, dict):
            rc2 = payload.get("reasoning_content")
            if isinstance(rc2, str) and rc2:
                return rc2

        # MiniMax-style thinking chunks.
        details = getattr(payload, "reasoning_details", None)
        if details is None and isinstance(payload, dict):
            details = payload.get("reasoning_details")
        from_details = cls._thinking_from_reasoning_details(details)
        if from_details:
            return from_details

        # OpenRouter-style fallback payloads (`reasoning` can be str/list/object).
        reasoning = getattr(payload, "reasoning", None)
        if reasoning is None and isinstance(payload, dict):
            reasoning = payload.get("reasoning")
        return cls._thinking_from_reasoning_details(reasoning)

    def _convert_messages(
        self, messages: list[dict[str, Any]], *, tools_present: bool = False
    ) -> list[dict[str, Any]]:
        """Convert messages to OpenAI format with multimodal support.

        Args:
            messages: Original messages

        Returns:
            OpenAI-formatted messages
        """
        openai_messages = []

        for msg in messages:
            role = msg.get("role", "user")

            # Already OpenAI-shaped rows from Agent._convert_history_to_provider
            if role == "tool" and "tool_call_id" in msg:
                tcid = msg.get("tool_call_id")
                if not tcid:
                    tcid = "empty_tool_call_id"
                c = msg.get("content", "")
                if c is None:
                    c = ""
                if not isinstance(c, str):
                    c = json.dumps(c, ensure_ascii=False)
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": str(tcid),
                    "content": c,
                })
                continue

            if role == "assistant" and msg.get("tool_calls"):
                row: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": msg["tool_calls"],
                }
                if "content" in msg:
                    row["content"] = msg["content"]
                else:
                    row["content"] = None
                openai_messages.append(row)
                continue

            content = msg.get("content", "")

            # Handle string content
            if isinstance(content, str):
                openai_messages.append(
                    self._get_compat_adapter().patch_message_row(
                        {"role": role, "content": content},
                        tools_present=tools_present,
                    )
                )
            # Handle structured content (images, files, etc.)
            elif isinstance(content, list):
                content_parts = []
                has_multimodal = False

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")

                        if block_type == "text":
                            content_parts.append({
                                "type": "text",
                                "text": block.get("content", ""),
                            })
                        elif block_type == "image":
                            # OpenAI image format
                            source_type = block.get("source_type", "base64")
                            media_type = block.get("media_type", "image/png")
                            data = block.get("data", "")
                            url = block.get("url")

                            if source_type == "url" and url:
                                content_parts.append({
                                    "type": "image_url",
                                    "image_url": {"url": url},
                                })
                                has_multimodal = True
                            elif source_type == "base64" and data:
                                content_parts.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{media_type};base64,{data}",
                                    },
                                })
                                has_multimodal = True
                        elif block_type == "file":
                            # Include file content as text
                            file_name = block.get("name", "unknown")
                            file_content = block.get("content", "")
                            mime_type = block.get("mime_type", "text/plain")

                            if file_content:
                                content_parts.append({
                                    "type": "text",
                                    "text": f"\n--- File: {file_name} ({mime_type}) ---\n{file_content}\n--- End of {file_name} ---\n",
                                })
                        elif block_type == "tool_result":
                            # Tool results are handled separately in OpenAI
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": (
                                    block.get("tool_call_id")
                                    or block.get("tool_use_id")
                                    or ""
                                ),
                                "content": block.get("content", ""),
                            })
                        else:
                            # Pass through other blocks as text
                            content_parts.append({
                                "type": "text",
                                "text": str(block),
                            })

                # Only add user message if we have content parts
                if content_parts:
                    if has_multimodal or len(content_parts) > 1:
                        openai_messages.append(
                            self._get_compat_adapter().patch_message_row(
                                {"role": role, "content": content_parts},
                                tools_present=tools_present,
                            )
                        )
                    else:
                        # Single text part, use simple string
                        openai_messages.append(
                            self._get_compat_adapter().patch_message_row(
                                {
                                    "role": role,
                                    "content": content_parts[0].get("text", ""),
                                },
                                tools_present=tools_present,
                            )
                        )

        return openai_messages

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool schemas to OpenAI format.

        Args:
            tools: Tool schemas in standard format

        Returns:
            OpenAI format tools
        """
        openai_tools = []

        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            }
            openai_tools.append(openai_tool)

        return openai_tools

    def _parse_arguments(self, arguments: str) -> dict | str:
        """Parse function call arguments.

        Args:
            arguments: Arguments JSON string

        Returns:
            Parsed arguments dict or original string if parsing fails
        """
        import json

        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments


def create_openai_provider(
    model: str = "gpt-4o",
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 4096,
    reasoning_effort: Literal["low", "medium", "high"] = "medium",
    caching_enabled: bool = True,
    timeout: float | int | None = None,
) -> OpenAIProvider:
    """Create an OpenAI provider instance.

    Args:
        model: Model identifier
        api_key: OpenAI API key
        base_url: Custom base URL
        max_tokens: Maximum tokens
        reasoning_effort: Reasoning effort level for O series models
        caching_enabled: Enable prompt caching (default: True)
        timeout: Optional request timeout in seconds for the HTTP client.

    Returns:
        OpenAIProvider instance
    """
    return OpenAIProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        caching_enabled=caching_enabled,
        timeout=timeout,
    )
