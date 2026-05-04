"""Anthropic Claude LLM provider implementation.

This module provides the Anthropic Claude provider implementation
using the official anthropic Python SDK.
"""

from __future__ import annotations

import ast
import json
from typing import Any, AsyncIterator

import anthropic
from anthropic import (
    AsyncAnthropic,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
    omit,
)

from ..base import (
    BaseProvider,
    BillingError,
    CacheStats,
    ProviderError,
    ProviderEvent,
    ProviderResponse,
    RateLimitError as AnthropicRateLimitError,
    TokenUsage,
    ToolCall,
)
from ...config.constants import ModelProvider
from ..claw_support.anthropic_resolve import (
    build_async_anthropic_client_kwargs,
    resolve_anthropic_token,
)

# Strict Bedrock-compatible gateways reject text blocks that are empty or whitespace-only.
_ANTHROPIC_MIN_VISIBLE_TEXT = "."


class AnthropicProvider(BaseProvider):
    """Anthropic Claude LLM provider.

    Supports:
    - Claude 3.5 Sonnet, Haiku
    - Claude 3 Opus
    - Tool calling
    - Streaming responses
    - Extended thinking (Claude 3.7 Sonnet)
    - Prompt Caching
    """

    # Models that support extended thinking
    THINKING_MODELS = {
        "claude-3-7-sonnet-20250214",
        "claude-3-7-sonnet-20250214:thinking",
    }

    # Number of recent messages to cache
    CACHE_MESSAGE_COUNT = 3

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        system_message: str = "",
        thinking_enabled: bool = False,
        thinking_budget_tokens: int | None = None,
        caching_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            model: Model identifier (e.g., claude-3-5-sonnet-20241022)
            api_key: Anthropic API key
            base_url: Custom base URL
            max_tokens: Maximum tokens for generation
            system_message: System message
            thinking_enabled: Enable extended thinking
            thinking_budget_tokens: Tokens to allocate for thinking
            caching_enabled: Enable prompt caching (default: True)
            **kwargs: Additional options
        """
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            system_message=system_message,
            **kwargs,
        )
        self.thinking_enabled = thinking_enabled
        self.thinking_budget_tokens = thinking_budget_tokens
        self.caching_enabled = caching_enabled

        # Initialize client
        self._client: AsyncAnthropic | None = None

    @staticmethod
    def _unfinished_tool_block_indices(tools_by_index: dict[int, ToolCall]) -> list[int]:
        """Indices of tool_use blocks that have not yet received content_block_stop."""
        return [i for i in sorted(tools_by_index.keys()) if not tools_by_index[i].finished]

    @staticmethod
    def _text_from_block_delta(delta: Any) -> str | None:
        """Extract assistant text from a ``content_block_delta`` inner delta.

        Some proxies omit or alter ``type``; accept plain ``text`` when unambiguous.
        """
        if delta is None:
            return None
        dt = getattr(delta, "type", None)
        if dt == "text_delta":
            return getattr(delta, "text", None) or ""
        if dt in ("thinking_delta", "input_json_delta", "signature_delta"):
            return None
        if getattr(delta, "partial_json", None) is not None:
            return None
        # Gateways may omit ``type`` but put reasoning in ``thinking``; do not surface as text.
        if getattr(delta, "thinking", None) and dt != "text_delta":
            return None
        chunk = getattr(delta, "text", None)
        if isinstance(chunk, str) and chunk:
            return chunk
        return None

    @staticmethod
    def _streaming_tool_input_prefix(current_input: Any) -> str:
        """Build prefix before concatenating ``input_json_delta`` ``partial_json`` chunks.

        Anthropic streams tool JSON as string fragments that must concatenate to one JSON
        object. When ``content_block_start`` sets ``input`` to an empty ``{}``, the
        prefix must be **empty** — using ``json.dumps({})`` would yield ``"{}"``, which
        prepended to the first fragment produces invalid JSON ``{}{"command":...}``.
        """
        if isinstance(current_input, dict):
            return "" if not current_input else json.dumps(current_input)
        return str(current_input or "")

    @staticmethod
    def _thinking_from_block_delta(delta: Any) -> str | None:
        if delta is None:
            return None
        dt = getattr(delta, "type", None)
        if dt == "thinking_delta":
            return getattr(delta, "thinking", None) or ""
        # Some compatible APIs omit ``type`` but stream ``thinking`` only (no ``text``).
        raw = getattr(delta, "thinking", None)
        if isinstance(raw, str) and raw and dt is None:
            if not getattr(delta, "text", None):
                return raw
        return None

    @classmethod
    def _resolve_stream_block_index(
        cls,
        tools_by_index: dict[int, ToolCall],
        event_index: int | None,
    ) -> int | None:
        """Map stream event index to tool buffer key; fallback if API omits index."""
        if event_index is not None:
            return event_index
        unf = cls._unfinished_tool_block_indices(tools_by_index)
        if len(unf) == 1:
            return unf[0]
        return None

    @property
    def client(self) -> AsyncAnthropic:
        """Get or create the Anthropic client.

        Uses Console API keys (``sk-ant-api…``) via ``api_key=``; OAuth and other
        tokens use ``auth_token=`` plus Claude Code–aligned beta headers (see
        ``claw_support.anthropic_resolve``).

        Returns:
            The async Anthropic client
        """
        if self._client is None:
            raw = (self.api_key or "").strip()
            if not raw:
                raw = (resolve_anthropic_token() or "").strip()
            if not raw:
                raise ValueError(
                    "Anthropic credentials are required. "
                    "Set ANTHROPIC_API_KEY, ANTHROPIC_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, "
                    "or Claude Code ~/.claude/.credentials.json, or pass api_key in settings."
                )

            client_kwargs = build_async_anthropic_client_kwargs(raw, self.base_url)
            self._client = AsyncAnthropic(**client_kwargs)
        return self._client

    async def send_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to Anthropic API.

        Args:
            messages: List of message dictionaries
            tools: Optional list of tool definitions

        Returns:
            Complete response
        """
        try:
            core_messages, system_text = self._split_system_from_messages(messages)
            # Convert messages to Anthropic format with caching
            anthropic_messages = self._convert_messages(
                core_messages, enable_caching=self.caching_enabled
            )

            # Convert tools to Anthropic format
            anthropic_tools = None
            if tools:
                anthropic_tools = [self._convert_tool(t) for t in tools]

            # Messages API: system is top-level only (strict gateways reject role=system rows).
            system = self._system_request_value(system_text)

            # Make the API call
            response = await self.client.messages.create(
                model=self.model,
                messages=anthropic_messages,
                system=system,
                tools=anthropic_tools,
                max_tokens=self.max_tokens,
                **self._get_thinking_params(),
            )

            # Parse response
            return self._parse_response(response)

        except RateLimitError as e:
            raise AnthropicRateLimitError(
                f"Rate limit exceeded: {e}",
                provider=ModelProvider.ANTHROPIC.value,
                model=self.model,
                original=e,
            )
        except (APIConnectionError, APITimeoutError) as e:
            raise ProviderError(
                f"Connection error: {e}",
                provider=ModelProvider.ANTHROPIC.value,
                model=self.model,
                original=e,
            )
        except APIStatusError as e:
            if getattr(e, "status_code", None) == 402 or "insufficient balance" in str(e).lower() or "payment required" in str(e).lower():
                raise BillingError(
                    "API account has insufficient balance. Please top up your API credits or check your billing plan.",
                    provider=ModelProvider.ANTHROPIC.value,
                    model=self.model,
                    original=e,
                )
            raise ProviderError(
                f"API error: {e}",
                provider=ModelProvider.ANTHROPIC.value,
                model=self.model,
                original=e,
            )

    async def stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream response from Anthropic API.

        Args:
            messages: List of message dictionaries
            tools: Optional list of tool definitions

        Yields:
            ProviderEvent objects
        """
        try:
            core_messages, system_text = self._split_system_from_messages(messages)
            # Convert messages to Anthropic format with caching
            anthropic_messages = self._convert_messages(
                core_messages, enable_caching=self.caching_enabled
            )

            # Convert tools to Anthropic format
            anthropic_tools = None
            if tools:
                anthropic_tools = [self._convert_tool(t) for t in tools]

            system = self._system_request_value(system_text)

            # Stream the API call
            stream = await self.client.messages.create(
                model=self.model,
                messages=anthropic_messages,
                system=system,
                tools=anthropic_tools,
                max_tokens=self.max_tokens,
                stream=True,
                **self._get_thinking_params(),
            )

            # Process the stream — buffer tool JSON by content block *index* so parallel
            # tool_use blocks do not corrupt each other's input (fixes missing file_path).
            content = ""
            thinking = ""
            tools_by_index: dict[int, ToolCall] = {}
            _fallback_block_index = 0
            last_stream_usage: Any = None

            async for event in stream:
                et = getattr(event, "type", None)

                # Cumulative usage on the wire (raw stream often omits ``message`` on message_stop).
                if et == "message_delta":
                    u = getattr(event, "usage", None)
                    if u is not None:
                        last_stream_usage = u
                    continue

                if et == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    think_chunk = self._thinking_from_block_delta(delta)
                    if think_chunk is not None:
                        thinking += think_chunk
                        yield ProviderEvent.thinking_delta(think_chunk)
                        continue
                    text_chunk = self._text_from_block_delta(delta)
                    if text_chunk is not None:
                        content += text_chunk
                        yield ProviderEvent.content_delta(text_chunk)
                        continue
                    if getattr(delta, "type", None) == "input_json_delta":
                        block_index = self._resolve_stream_block_index(
                            tools_by_index,
                            getattr(event, "index", None),
                        )
                        if block_index is None:
                            continue
                        current_tool = tools_by_index.get(block_index)
                        if not current_tool:
                            continue
                        partial_json = getattr(delta, "partial_json", None)
                        if partial_json:
                            prefix = self._streaming_tool_input_prefix(
                                current_tool.input
                            )
                            tools_by_index[block_index] = ToolCall(
                                id=current_tool.id,
                                name=current_tool.name,
                                input=prefix + str(partial_json),
                                finished=False,
                            )
                    continue

                if et == "content_block_start":
                    cb = getattr(event, "content_block", None)
                    if cb is not None and getattr(cb, "type", None) == "tool_use":
                        block_index = getattr(event, "index", None)
                        if block_index is None:
                            block_index = _fallback_block_index
                            _fallback_block_index += 1
                        initial_input = getattr(cb, "input", None)
                        parsed_initial_input: str | dict[str, Any]
                        if isinstance(initial_input, dict):
                            parsed_initial_input = initial_input
                        elif isinstance(initial_input, str):
                            parsed_initial_input = initial_input
                        else:
                            parsed_initial_input = ""
                        tc = ToolCall(
                            id=cb.id,
                            name=cb.name,
                            input=parsed_initial_input,
                            finished=False,
                        )
                        tools_by_index[block_index] = tc
                        yield ProviderEvent.tool_use_start(tc)
                    continue

                if et == "content_block_stop":
                    block_index = self._resolve_stream_block_index(
                        tools_by_index,
                        getattr(event, "index", None),
                    )
                    if block_index is None:
                        continue
                    current_tool = tools_by_index.get(block_index)
                    if current_tool and not current_tool.finished:
                        finalized = ToolCall(
                            id=current_tool.id,
                            name=current_tool.name,
                            input=self._parse_tool_input(current_tool.input),
                            finished=True,
                        )
                        tools_by_index[block_index] = finalized
                        yield ProviderEvent.tool_use_stop()
                    continue

                if et == "message_stop":
                    tool_calls = [
                        tools_by_index[i]
                        for i in sorted(tools_by_index.keys())
                    ]
                    msg = getattr(event, "message", None)
                    usage_src = getattr(msg, "usage", None) if msg is not None else None
                    if usage_src is None:
                        usage_src = last_stream_usage

                    if usage_src is None:
                        usage = TokenUsage(input_tokens=0, output_tokens=0)
                    else:
                        usage = TokenUsage(
                            input_tokens=int(
                                getattr(usage_src, "input_tokens", 0) or 0
                            ),
                            output_tokens=int(
                                getattr(usage_src, "output_tokens", 0) or 0
                            ),
                            cache_creation_tokens=int(
                                getattr(
                                    usage_src, "cache_creation_input_tokens", 0
                                )
                                or 0
                            ),
                            cache_read_tokens=int(
                                getattr(usage_src, "cache_read_input_tokens", 0)
                                or 0
                            ),
                        )

                    cache_stats = CacheStats(
                        cache_read_tokens=usage.cache_read_tokens,
                        cache_creation_tokens=usage.cache_creation_tokens,
                        cached=usage.cache_read_tokens > 0,
                    )

                    response = ProviderResponse(
                        content=content,
                        thinking=thinking,
                        tool_calls=tool_calls,
                        usage=usage,
                        finish_reason="stop",
                        model=self.model,
                        cache_stats=cache_stats,
                    )

                    yield ProviderEvent.complete(response)

        except Exception as e:
            yield ProviderEvent.error(e)

    def _parse_tool_input(self, value: str | dict[str, Any] | Any) -> dict[str, Any] | str:
        """Parse tool input from Anthropic/compatible streaming events."""
        if isinstance(value, dict):
            return value
        raw = str(value or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return raw

    @staticmethod
    def _tool_result_body(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)

    @classmethod
    def _openai_history_to_anthropic_messages(
        cls,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Agent emits OpenAI-shaped rows (``role: tool``, ``tool_calls``). Anthropic only allows
        ``user`` / ``assistant``; tool outputs must be ``user`` turns with ``tool_result`` blocks.
        """
        out: list[dict[str, Any]] = []
        i = 0
        n = len(messages)
        while i < n:
            msg = messages[i]
            role = msg.get("role", "user")

            if role == "tool":
                blocks: list[dict[str, Any]] = []
                while i < n and messages[i].get("role") == "tool":
                    tm = messages[i]
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": str(
                                tm.get("tool_call_id") or tm.get("tool_use_id") or ""
                            ),
                            "content": cls._tool_result_body(tm.get("content")),
                        }
                    )
                    i += 1
                out.append({"role": "user", "content": blocks})
                continue

            if role == "assistant" and msg.get("tool_calls"):
                parts: list[dict[str, Any]] = []
                raw_text = msg.get("content")
                if isinstance(raw_text, str) and raw_text.strip():
                    parts.append({"type": "text", "text": raw_text})
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            inp: Any = json.loads(args) if args.strip() else {}
                        except json.JSONDecodeError:
                            inp = {}
                    elif isinstance(args, dict):
                        inp = args
                    else:
                        inp = {}
                    if not isinstance(inp, dict):
                        inp = {"value": inp}
                    parts.append(
                        {
                            "type": "tool_use",
                            "id": str(tc.get("id") or ""),
                            "name": name,
                            "input": inp,
                        }
                    )
                out.append({"role": "assistant", "content": parts})
                i += 1
                continue

            out.append(dict(msg))
            i += 1

        return out

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
        enable_caching: bool = True,
    ) -> list[dict[str, Any]]:
        """Convert messages to Anthropic format with optional caching.

        Args:
            messages: Original messages
            enable_caching: Whether to enable prompt caching

        Returns:
            Anthropic-formatted messages with cache controls
        """
        messages = self._openai_history_to_anthropic_messages(messages)
        anthropic_messages = []
        total_messages = len(messages)

        for idx, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Determine if this message should be cached
            # Cache the last CACHE_MESSAGE_COUNT messages (excluding the most recent)
            should_cache = (
                enable_caching
                and self.caching_enabled
                and total_messages > self.CACHE_MESSAGE_COUNT
                and idx >= total_messages - self.CACHE_MESSAGE_COUNT - 1
                and idx < total_messages - 1  # Don't cache the last (current) message
            )

            # Handle string content
            if isinstance(content, str):
                ctext = content
                if not ctext.strip():
                    # Bedrock-style validators reject empty or whitespace-only text bodies.
                    ctext = _ANTHROPIC_MIN_VISIBLE_TEXT
                message_content = {"role": role, "content": ctext}
                if should_cache:
                    message_content["cache_control"] = {"type": "ephemeral"}
                anthropic_messages.append(message_content)
            # Handle structured content (tool results, images, files, etc.)
            elif isinstance(content, list):
                blocks = []
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")

                        if block_type == "tool_result":
                            tr_body = block.get("content", "")
                            if not isinstance(tr_body, str):
                                tr_body = json.dumps(tr_body, ensure_ascii=False)
                            # Strict gateways reject empty tool_result / text bodies.
                            if not (tr_body or "").strip():
                                tr_body = _ANTHROPIC_MIN_VISIBLE_TEXT
                            blocks.append({
                                "type": "tool_result",
                                "tool_use_id": block.get("tool_use_id"),
                                "content": tr_body,
                            })
                        elif block_type == "image":
                            # Convert to Anthropic image format
                            source_type = block.get("source_type", "base64")
                            media_type = block.get("media_type", "image/png")
                            data = block.get("data", "")

                            if source_type == "base64":
                                blocks.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": data,
                                    },
                                })
                            elif source_type == "url" and block.get("url"):
                                # Anthropic doesn't support URLs directly,
                                # we'd need to download and convert to base64
                                # For now, skip URL images
                                pass
                        elif block_type == "file":
                            # Include file content as text
                            file_name = block.get("name", "unknown")
                            file_content = block.get("content", "")
                            mime_type = block.get("mime_type", "text/plain")

                            if file_content:
                                # Add file content as text with header
                                blocks.append({
                                    "type": "text",
                                    "text": f"\n--- File: {file_name} ({mime_type}) ---\n{file_content}\n--- End of {file_name} ---\n",
                                })
                        elif block_type == "text":
                            ttxt = block.get("text") or block.get("content") or ""
                            if isinstance(ttxt, str) and ttxt.strip():
                                blocks.append({"type": "text", "text": ttxt})
                        elif block_type == "tool_use":
                            blocks.append(block)
                        else:
                            blocks.append(block)

                if not blocks:
                    continue
                message_content = {"role": role, "content": blocks}
                if should_cache:
                    message_content["cache_control"] = {"type": "ephemeral"}
                anthropic_messages.append(message_content)

        return anthropic_messages

    @staticmethod
    def _split_system_from_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str]:
        """Remove ``role: system`` rows; Anthropic Messages API uses top-level ``system`` only."""
        parts: list[str] = []
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    if content.strip():
                        parts.append(content)
                elif isinstance(content, list):
                    chunk: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            chunk.append(
                                str(block.get("text") or block.get("content") or "")
                            )
                    joined = "\n".join(c for c in chunk if c)
                    if joined.strip():
                        parts.append(joined)
            else:
                out.append(msg)
        return out, "\n\n".join(parts)

    def _system_request_value(self, system_from_messages: str) -> Any:
        """Build the ``system`` field for ``messages.create`` (never use role=system in ``messages``)."""
        combined = "\n\n".join(
            s
            for s in (system_from_messages, self.system_message)
            if isinstance(s, str) and s.strip()
        ).strip()
        if not combined:
            return omit

        # Official API accepts str | list of blocks; some proxies (e.g. Bedrock-backed
        # gateways) validate ``system`` as a list only — always use a one-element list.
        block: dict[str, Any] = {"type": "text", "text": combined}
        if self.caching_enabled:
            block = {
                "type": "text",
                "text": combined,
                "cache_control": {"type": "ephemeral"},
            }
        return [block]

    def _convert_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Convert tool to Anthropic format.

        Args:
            tool: Tool definition

        Returns:
            Anthropic-formatted tool
        """
        if "function" in tool:
            # OpenAI-style format
            func = tool["function"]
            params = func.get("parameters") or {}
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}}
            return {
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": params,
            }
        # ToolInfo.to_dict() from Agent: name/description/parameters (no ``function`` wrap).
        # Some Claude proxies (e.g. Bedrock-backed gateways) require ``input_schema`` and
        # reject payloads that only send ``parameters``.
        if (
            "name" in tool
            and "input_schema" not in tool
            and "parameters" in tool
        ):
            params = tool.get("parameters") or {}
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}}
            elif not params:
                params = {"type": "object", "properties": {}}
            return {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": params,
            }
        return tool

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse Anthropic response.

        Args:
            response: Raw Anthropic response

        Returns:
            Provider response
        """
        content = ""
        thinking = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "thinking":
                thinking += block.thinking
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                        finished=True,
                    )
                )

        # Extract cache-related usage if available
        cache_creation_tokens = getattr(
            response.usage, "cache_creation_input_tokens", 0
        ) or 0
        cache_read_tokens = getattr(
            response.usage, "cache_read_input_tokens", 0
        ) or 0

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
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
            finish_reason=response.stop_reason,
            model=response.model,
            cache_stats=cache_stats,
        )

    def _get_thinking_params(self) -> dict[str, Any]:
        """Get thinking-related parameters.

        Returns:
            Dictionary of thinking parameters
        """
        params = {}

        if self.thinking_enabled and self.model in self.THINKING_MODELS:
            if self.thinking_budget_tokens:
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.thinking_budget_tokens,
                }
            else:
                params["thinking"] = {"type": "enabled"}

        return params

    @property
    def supports_thinking(self) -> bool:
        """Check if this model supports extended thinking.

        Returns:
            True if thinking is supported
        """
        return self.model in self.THINKING_MODELS


def create_anthropic_provider(
    model: str,
    api_key: str | None = None,
    caching_enabled: bool = True,
    **kwargs: Any,
) -> AnthropicProvider:
    """Factory function to create an Anthropic provider.

    Args:
        model: Model identifier
        api_key: API key
        caching_enabled: Enable prompt caching (default: True)
        **kwargs: Additional provider options

    Returns:
        AnthropicProvider instance
    """
    return AnthropicProvider(
        model=model,
        api_key=api_key,
        caching_enabled=caching_enabled,
        **kwargs,
    )
