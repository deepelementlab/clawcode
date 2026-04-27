"""Agent ReAct loop implementation.

This module provides the core Agent class that implements the
ReAct (Reasoning + Acting) pattern for AI agent behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import hashlib
import re
import time
from collections import defaultdict
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from .base import BaseProvider, ProviderEvent, ProviderEventType, ToolCall, TokenUsage
from .claw_support.iteration_budget import IterationBudget
from .plan_policy import is_tool_allowed_in_plan_mode
from .tool_input_validate import pilot_validate_tool_input
from .tools import BaseTool, ToolContext, ToolResponse
from .prompts import get_system_prompt
from ..config import get_settings
from ..claw_learning.ops_observability import emit_ops_event
from ..learning.store import record_tool_observation_async
from ..plugin.types import HookEvent
from ..utils.text import sanitize_text
from ..config.settings import Settings

try:
    from ..plugin.hooks import HookEngine
except Exception:  # pragma: no cover
    HookEngine = Any  # type: ignore[assignment]

from ..message import (
    MessageService,
    Message,
    MessageRole,
    ContentPart,
    TextContent,
    ThinkingContent,
    ImageContent,
    FileContent,
    ToolCallContent,
)
from ..session import SessionService


class AgentEventType(Enum):
    """Agent event types."""

    THINKING = "thinking"
    CONTENT_DELTA = "content_delta"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    RESPONSE = "response"
    ERROR = "error"


@dataclass
class AgentEvent:
    """Event from the Agent during ReAct loop.

    Attributes:
        type: Event type
        message: Associated message (if available)
        content: Content delta (for CONTENT_DELTA events)
        tool_name: Tool name (for tool events)
        tool_input: Tool input (for TOOL_USE events)
        tool_result: Tool result (for TOOL_RESULT events)
        is_error: Whether tool result is an error
        error: Error message (for ERROR events)
        done: Whether processing is complete
    """

    type: AgentEventType
    message: Message | None = None
    content: str | None = None
    usage: TokenUsage | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_stream: str | None = None  # "stdout" | "stderr" | None
    tool_returncode: int | None = None
    tool_elapsed: float | None = None
    tool_timeout: bool = False
    tool_input: dict | str | None = None
    tool_result: str | None = None
    is_error: bool = False
    tool_done: bool = False
    error: str | None = None
    done: bool = False
    # When True, TUI should update HUD aggregates only (no message_list tool rows).
    hud_only: bool = False

    @classmethod
    def thinking(cls, message: Message) -> "AgentEvent":
        """Create a thinking event.

        Args:
            message: Message with thinking content

        Returns:
            Thinking event
        """
        return cls(type=AgentEventType.THINKING, message=message)

    @classmethod
    def content_delta(cls, content: str) -> "AgentEvent":
        """Create a content delta event.

        Args:
            content: Content delta

        Returns:
            Content delta event
        """
        return cls(type=AgentEventType.CONTENT_DELTA, content=content)

    @classmethod
    def tool_use(cls, tool_name: str, tool_input: dict | str) -> "AgentEvent":
        """Create a tool use event.

        Args:
            tool_name: Tool name
            tool_input: Tool input

        Returns:
            Tool use event
        """
        return cls(
            type=AgentEventType.TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input,
        )

    @classmethod
    def tool_use_with_id(
        cls,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict | str,
    ) -> "AgentEvent":
        return cls(
            type=AgentEventType.TOOL_USE,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
        )

    @classmethod
    def tool_result(
        cls,
        tool_name: str,
        tool_call_id: str,
        result: str,
        is_error: bool = False,
        tool_done: bool = True,
        tool_stream: str | None = None,
        tool_returncode: int | None = None,
        tool_elapsed: float | None = None,
        tool_timeout: bool = False,
    ) -> "AgentEvent":
        """Create a tool result event.

        Args:
            tool_name: Tool name
            result: Tool result
            is_error: Whether result is an error

        Returns:
            Tool result event
        """
        return cls(
            type=AgentEventType.TOOL_RESULT,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_stream=tool_stream,
            tool_result=result,
            is_error=is_error,
            tool_done=tool_done,
            tool_returncode=tool_returncode,
            tool_elapsed=tool_elapsed,
            tool_timeout=tool_timeout,
        )

    @classmethod
    def response(cls, message: Message) -> "AgentEvent":
        """Create a response event.

        Args:
            message: Complete message

        Returns:
            Response event
        """
        return cls(
            type=AgentEventType.RESPONSE,
            message=message,
            done=True,
        )

    @classmethod
    def error(cls, error: str) -> "AgentEvent":
        """Create an error event.

        Args:
            error: Error message

        Returns:
            Error event
        """
        return cls(
            type=AgentEventType.ERROR,
            error=error,
            done=True,
        )


_TOOL_OUTPUT_MAX_CHARS = 8000
_ARTIFACT_PREVIEW_CHARS = 200
_logger = logging.getLogger(__name__)

# Regexes to strip tool-call-like JSON that leaks into the LLM content stream.
_LEAKED_TOOL_JSON_RE = re.compile(
    r"(TodoWrite|TaskCreate|TaskUpdate|UpdateProjectState)\s*[\[{].*?[}\]]",
    re.DOTALL,
)
_LEAKED_TOOL_LINE_RE = re.compile(
    r">\s*(bash|ls|write|edit|view|grep|glob|patch|fetch|mcp_call)\s+\{.*?\}",
    re.DOTALL,
)


def _strip_leaked_tool_json(text: str) -> str:
    """Remove tool-call-like JSON/repr that leaks into content stream."""
    if not text:
        return text
    text = _LEAKED_TOOL_JSON_RE.sub("", text)
    text = _LEAKED_TOOL_LINE_RE.sub("", text)
    # Collapse excessive blank lines left behind
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _normalize_tool_message_sequences_for_api(
    messages: list[dict[str, Any]],
    *,
    start_from: int = 0,
) -> None:
    """Ensure strict OpenAI / DeepSeek ordering: one ``tool`` row per ``tool_calls[].id``.

    Rebuilds the in-place list so that after each assistant message with ``tool_calls``,
    tool responses appear in the same order as ``tool_calls``, padding synthetic rows
    when results are missing or ids were reordered.

    When ``start_from`` is given, only messages from that index onward are rescanned;
    earlier messages are left untouched.
    """
    if start_from <= 0:
        prefix: list[dict[str, Any]] = []
        tail = messages
    else:
        prefix = list(messages[:start_from])
        tail = messages[start_from:]

    i = 0
    out: list[dict[str, Any]] = []
    while i < len(tail):
        m = tail[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            out.append(m)
            required: list[str] = []
            for tc in m["tool_calls"]:
                if isinstance(tc, dict) and tc.get("id"):
                    required.append(str(tc["id"]))
            i += 1
            bodies: dict[str, list[str]] = defaultdict(list)
            while i < len(tail) and tail[i].get("role") == "tool":
                row = tail[i]
                tid = str(row.get("tool_call_id") or "")
                bodies[tid].append(str(row.get("content") if row.get("content") is not None else ""))
                i += 1
            for rid in required:
                queue = bodies.get(rid)
                if queue:
                    content = queue.pop(0)
                else:
                    content = "Error: missing tool output for this call."
                out.append({
                    "role": "tool",
                    "tool_call_id": rid,
                    "content": content,
                })
            continue
        out.append(m)
        i += 1
    messages[:] = prefix + out


def _heal_orphan_tool_rows_before_send(
    messages: list[dict[str, Any]],
) -> tuple[int, int]:
    """Drop orphan ``tool`` rows and ensure each assistant tool_call has a result row.

    Returns:
        (dropped_orphans, synthesized_missing_rows)
    """
    out: list[dict[str, Any]] = []
    dropped = 0
    synthesized = 0
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            out.append(m)
            required: list[str] = []
            for tc in m.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id"):
                    required.append(str(tc["id"]))
            i += 1
            bodies: dict[str, list[str]] = defaultdict(list)
            while i < len(messages) and messages[i].get("role") == "tool":
                row = messages[i]
                tid = str(row.get("tool_call_id") or "")
                if tid in required:
                    bodies[tid].append(str(row.get("content") if row.get("content") is not None else ""))
                else:
                    dropped += 1
                i += 1
            for rid in required:
                queue = bodies.get(rid)
                if queue:
                    content = queue.pop(0)
                else:
                    content = "Error: missing tool output for this call."
                    synthesized += 1
                out.append({
                    "role": "tool",
                    "tool_call_id": rid,
                    "content": content,
                })
            continue

        if m.get("role") == "tool":
            dropped += 1
            i += 1
            continue

        out.append(m)
        i += 1
    messages[:] = out
    return dropped, synthesized


def _persisted_tool_result_dict(
    tool_call: ToolCall, content: str, is_error: bool
) -> dict[str, Any]:
    """Shape stored on TOOL messages; replay can rebuild assistant ``tool_calls`` for strict APIs."""
    try:
        arg_str = json.dumps(tool_call.get_input_dict(), ensure_ascii=False)
    except (TypeError, ValueError):
        arg_str = "{}"
    return {
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "arguments": arg_str,
        "content": content,
        "is_error": is_error,
    }


def _desktop_screenshot_paths_from_persisted_results(
    results: list[dict[str, Any]],
) -> list[str]:
    """Collect paths from successful ``desktop_screenshot`` JSON tool rows (for vision auto-attach)."""
    paths: list[str] = []
    for row in results:
        if (row.get("name") or "") != "desktop_screenshot":
            continue
        if row.get("is_error"):
            continue
        body = row.get("content")
        if not isinstance(body, str) or not body.strip():
            continue
        try:
            d = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict) or d.get("ok") is not True:
            continue
        p = d.get("screenshot_path")
        if isinstance(p, str) and p.strip():
            paths.append(p.strip())
    return paths


class Agent:
    """AI Agent with ReAct loop.

    The Agent manages conversation with the LLM, tool execution,
    and multi-turn interaction.
    """

    def __init__(
        self,
        provider: BaseProvider,
        tools: list[BaseTool],
        message_service: MessageService,
        session_service: SessionService,
        system_prompt: str | None = None,
        max_iterations: int = 100,
        working_directory: str | None = None,
        hook_engine: HookEngine | None = None,
        summarizer: Any | None = None,
        settings: Settings | None = None,
        permission_client: Any | None = None,
    ) -> None:
        """Initialize the Agent.

        Args:
            provider: LLM provider
            tools: Available tools
            message_service: Message service
            session_service: Session service
            system_prompt: System prompt (uses default if None)
            max_iterations: Maximum ReAct loop iterations
            working_directory: Working directory for tools
            hook_engine: Plugin hook engine
            summarizer: Optional SummarizerService for auto-compacting long conversations
            permission_client: Same object passed to ``get_builtin_tools(permissions=...)``;
                exposed on :class:`~clawcode.llm.tools.base.ToolContext` as ``permission_service``.
        """
        self._provider = provider
        # One schema per physical tool; aliases (Task -> Agent) share the same instance.
        _seen: set[int] = set()
        _unique_tools: list[BaseTool] = []
        for _t in tools:
            _tid = id(_t)
            if _tid in _seen:
                continue
            _seen.add(_tid)
            _unique_tools.append(_t)
        self._tools_unique = _unique_tools
        self._tools = {t.info().name: t for t in self._tools_unique}
        if "Agent" in self._tools:
            self._tools["Task"] = self._tools["Agent"]
        # Alias mapping for common LLM-trained tool names that differ from our naming
        if "batch_view" in self._tools:
            self._tools["read_important_files_batch"] = self._tools["batch_view"]
        self._message_service = message_service
        self._session_service = session_service
        self._system_prompt = system_prompt or get_system_prompt("coder")
        self._max_iterations = max_iterations
        self._hook_engine = hook_engine
        self._summarizer = summarizer
        self._permission_client = permission_client
        self._settings = settings
        if self._settings is None:
            try:
                self._settings = get_settings()
            except Exception:
                self._settings = None
        # Tools 运行所需的工作目录（例如 bash/ls 等）
        # 默认为当前进程的工作目录，允许上层显式注入。
        import os

        self._working_directory = working_directory or os.getcwd()

        # Track active requests
        self._active_requests: dict[str, asyncio.Task] = {}
        # Closed-loop learning nudges
        self._turns_since_memory = 0
        self._iters_since_skill = 0
        self._memory_nudge_interval = 10
        self._skill_nudge_interval = 15
        self._memory_flush_max_writes = 2
        self._flush_budget_enabled = True
        self._flush_duplicate_suppression = True
        if self._settings is not None:
            cl = self._settings.closed_loop
            self._flush_budget_enabled = bool(cl.flush_budget_enabled)
            self._memory_flush_max_writes = int(cl.flush_max_writes)
            self._flush_duplicate_suppression = bool(cl.flush_duplicate_suppression)
        self._ephemeral_user_suffix = ""
        self._ephemeral_user_target_id: str | None = None
        self._reset_closed_loop_metrics()
        self._cached_tool_schemas: list[dict[str, Any]] | None = None
        self._provider_messages_cache: list[dict[str, Any]] = []
        self._provider_messages_cache_len: int = 0
        self._bg_provider_messages_cache: list[dict[str, Any]] = []
        self._bg_provider_messages_cache_len: int = 0
        self._bg_provider_messages_cache_session_id: str | None = None
        self._last_flush_time: float = 0.0
        self._flush_cooldown: float = 60.0
        self._YIELD_INTERVAL: float = 0.05
        _max_tools = int(getattr(settings, "max_concurrent_tools", 5)) if settings else 5
        _max_sub = int(getattr(settings, "max_concurrent_subagents", 3)) if settings else 3
        self._tool_semaphore = asyncio.Semaphore(max(1, _max_tools))
        self._subagent_semaphore = asyncio.Semaphore(max(1, _max_sub))
        # Read-only tool result cache to avoid redundant calls within a single Agent run
        self._tool_result_cache: dict[str, ToolResponse] = {}

    def _reset_closed_loop_metrics(self) -> None:
        """Per-run observability counters for closed-loop behavior."""
        self._metric_memory_nudge_triggered = 0
        self._metric_skill_nudge_triggered = 0
        self._metric_memory_flush_attempts = 0
        self._metric_memory_flush_success = 0
        self._metric_memory_flush_budget_hits = 0
        self._metric_memory_flush_duplicate_skips = 0
        self._metric_memory_reset_hits = 0
        self._metric_skill_reset_hits = 0
        self._metric_provider_bg_cache_hits = 0
        self._metric_provider_bg_cache_misses = 0
        self._metric_provider_bg_cache_resets = 0
        self._metric_provider_normalize_full_fallbacks = 0
        self._metric_provider_orphan_tool_healed_count = 0
        self._metric_provider_orphan_tool_dropped_count = 0

    @property
    def provider(self) -> BaseProvider:
        """Get the LLM provider.

        Returns:
            Provider instance
        """
        return self._provider

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        if self._cached_tool_schemas is None:
            self._cached_tool_schemas = [t.info().to_dict() for t in self._tools_unique]
        return self._cached_tool_schemas

    def _maybe_save_artifact(
        self, session_id: str, tool_call_id: str, content: str
    ) -> str:
        """Save oversized tool output to an artifact file, returning a short reference.

        If *content* is within limits it is returned unchanged.
        """
        if len(content) <= _TOOL_OUTPUT_MAX_CHARS:
            return content
        try:
            artifacts_dir = Path(self._working_directory) / ".clawcode" / "artifacts" / session_id
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifacts_dir / f"{tool_call_id}.log"
            artifact_path.write_text(content, encoding="utf-8")
            line_count = content.count("\n") + 1
            preview = content[:_ARTIFACT_PREVIEW_CHARS].rstrip()
            return (
                f"[Output too long ({len(content)} chars, {line_count} lines). "
                f"Saved to {artifact_path.relative_to(Path(self._working_directory))}. "
                f"Use `view` to read it.]\n{preview}\n..."
            )
        except Exception as exc:
            _logger.debug("Failed to save artifact: %s", exc)
            return content[:_TOOL_OUTPUT_MAX_CHARS] + "\n... (truncated)"

    async def _refresh_history(self, session_id: str) -> list[Message]:
        """Reload session history from message storage."""
        return await self._message_service.list_by_session(session_id)

    async def _auto_compact_history(
        self,
        session_id: str,
        history: list[Message],
    ) -> list[Message]:
        """Best-effort context compaction for strict context-window providers."""
        if not self._summarizer or not history:
            return history
        model = getattr(self._provider, "model", None)
        try:
            now = time.monotonic()
            if now - self._last_flush_time >= self._flush_cooldown:
                self._last_flush_time = now
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        self._flush_memories_before_compact(session_id, history)
                    )
                except RuntimeError:
                    pass
            compact_result = await self._summarizer.maybe_summarize(
                session_id,
                history,
                model=model,
            )
            if compact_result:
                return await self._refresh_history(session_id)

            # If still above threshold, force a compact pass as fallback.
            summarizer_obj = None
            if hasattr(self._summarizer, "_get_summarizer"):
                try:
                    summarizer_obj = self._summarizer._get_summarizer()
                except Exception:
                    summarizer_obj = None
            if summarizer_obj is not None:
                session = await self._session_service.get(session_id)
                if session and await summarizer_obj.should_summarize(session, history, model):
                    forced = await self._summarizer.force_summarize(session_id, history)
                    if forced:
                        return await self._refresh_history(session_id)
        except Exception:
            return history
        return history

    async def _flush_memories_before_compact(self, session_id: str, history: list[Message]) -> None:
        """One-shot restricted flush: allow only memory tool before compact."""
        memory_tool = self._tools.get("memory")
        if not memory_tool or not history:
            return
        self._metric_memory_flush_attempts += 1
        flush_prompt = (
            "[System: Context may be summarized soon. Save durable user preferences, corrections, "
            "and stable environment facts to memory. Avoid temporary task progress.]"
        )
        temp_history = list(history)
        flush_msg = await self._create_user_message(session_id=session_id, content=flush_prompt, attachments=None)
        temp_history.append(flush_msg)
        tool_schemas = [memory_tool.info().to_dict()]
        provider_messages = self._convert_history_to_provider(
            temp_history,
            tools_present=True,
            use_incremental_cache=True,
            cache_scope="background",
            cache_session_id=session_id,
        )
        tool_calls: list[ToolCall] = []
        try:
            async for ev in self._provider.stream_response(provider_messages, tool_schemas):
                if ev.type == ProviderEventType.COMPLETE and ev.response and ev.response.tool_calls:
                    tool_calls.extend(ev.response.tool_calls)
            if not tool_calls:
                return
            _dummy_results: list[dict[str, Any]] = []
            flush_succeeded = False
            writes = 0
            seen_signatures: set[str] = set()
            for tc in tool_calls:
                if tc.name != "memory":
                    continue
                if self._flush_budget_enabled and writes >= self._memory_flush_max_writes:
                    self._metric_memory_flush_budget_hits += 1
                    continue
                sig = hashlib.sha1(
                    json.dumps(tc.get_input_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if self._flush_duplicate_suppression and sig in seen_signatures:
                    self._metric_memory_flush_duplicate_skips += 1
                    continue
                seen_signatures.add(sig)
                ctx = ToolContext(
                    session_id=session_id,
                    message_id="",
                    working_directory=self._working_directory,
                    permission_service=self._permission_client,
                    plan_mode=False,
                    iteration_budget=None,
                )
                resp = await memory_tool.run(tc, ctx)
                _dummy_results.append(
                    {
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "arguments": tc.get_input_dict(),
                        "content": resp.content,
                        "is_error": bool(resp.is_error),
                    }
                )
                flush_succeeded = flush_succeeded or (not bool(resp.is_error))
                self._on_tool_used(tc.name)
                writes += 1
            if flush_succeeded:
                self._metric_memory_flush_success += 1
        except Exception:
            return

    def _on_tool_used(self, tool_name: str) -> None:
        if tool_name == "memory":
            self._turns_since_memory = 0
            self._metric_memory_reset_hits += 1
        elif tool_name == "skill_manage":
            self._iters_since_skill = 0
            self._metric_skill_reset_hits += 1

    def _build_ephemeral_nudge_suffix(self) -> str:
        chunks: list[str] = []
        if "memory" in self._tools:
            self._turns_since_memory += 1
            if self._memory_nudge_interval > 0 and self._turns_since_memory >= self._memory_nudge_interval:
                chunks.append(
                    "[System: You've had several exchanges. Consider whether the user shared preferences, "
                    "corrections, or workflow facts worth saving with the memory tool.]"
                )
                self._metric_memory_nudge_triggered += 1
                self._turns_since_memory = 0
        if "skill_manage" in self._tools and self._iters_since_skill >= self._skill_nudge_interval:
            chunks.append(
                "[System: The previous task involved many tool calls. Save the approach as a reusable skill, "
                "or patch existing skill instructions if they were incomplete.]"
            )
            self._metric_skill_nudge_triggered += 1
            self._iters_since_skill = 0
        if not chunks:
            return ""
        return "\n\n" + "\n\n".join(chunks)

    async def run(
        self,
        session_id: str,
        content: str,
        attachments: list[Any] | None = None,
        *,
        plan_mode: bool = False,
        iteration_budget: IterationBudget | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the Agent ReAct loop.

        Events are yielded **as they arrive** from the provider so
        the UI can display content with a streaming / typewriter effect.

        Args:
            session_id: Session ID
            content: User message content
            attachments: Optional attachments
            plan_mode: When True, restrict tools to read-only plan policy.
            iteration_budget: Optional Claw-style shared cap: one ``consume()`` per
                LLM round (after ``iteration`` increments). When exhausted, yields
                ``ERROR`` and stops. If ``None``, only ``max_iterations`` applies.

        Yields:
            AgentEvent objects (THINKING, CONTENT_DELTA, TOOL_USE,
            TOOL_RESULT, RESPONSE, ERROR)
        """
        if session_id in self._active_requests:
            yield AgentEvent.error(f"Session {session_id} is busy")
            return

        self._active_requests[session_id] = True
        self._reset_closed_loop_metrics()

        try:
            # --- Hook: SessionStart ---
            if self._hook_engine:
                await self._hook_engine.fire(
                    HookEvent.SessionStart,
                    context={"session_id": session_id, "startup": "new"},
                    provider=self._provider,
                    working_directory=self._working_directory,
                    suppress_agent_hooks=True,
                )

            history = await self._message_service.list_by_session(session_id)
            # Optional DeepNote auto-orient context injection.
            try:
                dcfg = getattr(self._settings, "deepnote", None)
                if dcfg and bool(getattr(dcfg, "enabled", False)) and bool(getattr(dcfg, "auto_orient", False)):
                    from ..deepnote.wiki_store import WikiStore

                    store = WikiStore.from_settings(self._settings)
                    if store.exists():
                        stats = store.get_stats()
                        orient_hint = (
                            "\n\n[DeepNote auto-orient]\n"
                            f"wiki_root={stats.get('root','')}\n"
                            f"total_pages={stats.get('total_pages',0)}\n"
                            "For wiki tasks, call wiki_orient first, then wiki_query/wiki_ingest/wiki_lint as needed."
                        )
                        content = (content or "") + orient_hint
            except Exception:
                pass

            # Auto-compact: summarize early messages when approaching context limits.
            history = await self._auto_compact_history(session_id, history)

            user_msg = await self._create_user_message(
                session_id=session_id,
                content=content,
                attachments=attachments,
            )
            history.append(user_msg)
            self._ephemeral_user_target_id = user_msg.id
            self._ephemeral_user_suffix = self._build_ephemeral_nudge_suffix()

            # --- Hook: UserPromptSubmit ---
            if self._hook_engine:
                await self._hook_engine.fire(
                    HookEvent.UserPromptSubmit,
                    context={
                        "session_id": session_id,
                        "prompt": content,
                        "attachments": [getattr(a, "path", None) for a in attachments or []],
                    },
                    provider=self._provider,
                    working_directory=self._working_directory,
                    suppress_agent_hooks=True,
                )

            iteration = 0
            while iteration < self._max_iterations:
                iteration += 1
                if "skill_manage" in self._tools and self._skill_nudge_interval > 0:
                    self._iters_since_skill += 1

                if iteration_budget is not None and not iteration_budget.consume():
                    yield AgentEvent.error(
                        "Iteration budget exhausted (shared Claw iteration cap)."
                    )
                    break

                # Emit a lightweight thinking hint so the TUI shows
                # activity while waiting for the LLM's first token.
                if iteration > 1:
                    yield AgentEvent(
                        type=AgentEventType.THINKING,
                        content="",
                    )
                    await asyncio.sleep(0)

                try:
                    assistant_msg = await self._message_service.create(
                        session_id=session_id,
                        role=MessageRole.ASSISTANT,
                    )

                    tool_schemas = self._get_tool_schemas()
                    provider_messages = self._convert_history_to_provider(
                        history,
                        tools_present=bool(tool_schemas),
                        cache_scope="main",
                        cache_session_id=session_id,
                    )
                    if tool_schemas:
                        dropped, synthesized = _heal_orphan_tool_rows_before_send(provider_messages)
                        if dropped or synthesized:
                            self._metric_provider_orphan_tool_dropped_count += dropped
                            self._metric_provider_orphan_tool_healed_count += synthesized
                            _logger.warning(
                                "Healed provider messages before send: dropped_orphan_tool=%s synthesized_missing_tool=%s session=%s",
                                dropped,
                                synthesized,
                                session_id,
                            )
                    tool_calls: list[ToolCall] = []
                    stream_failed: str | None = None
                    _last_yield_time = time.monotonic()

                    async for event in self._provider.stream_response(
                        provider_messages, tool_schemas
                    ):
                        match event.type:
                            case ProviderEventType.ERROR:
                                err = event.error
                                stream_failed = str(err) if err else "Provider stream error"
                                yield AgentEvent.error(stream_failed)
                                break

                            case ProviderEventType.CONTENT_DELTA:
                                delta = event.content or ""
                                delta = _strip_leaked_tool_json(delta)
                                assistant_msg.parts.append(TextContent(content=delta))
                                yield AgentEvent.content_delta(delta)
                                now = time.monotonic()
                                if now - _last_yield_time >= self._YIELD_INTERVAL:
                                    await asyncio.sleep(0)
                                    _last_yield_time = now

                            case ProviderEventType.THINKING_DELTA:
                                thinking = event.thinking or ""
                                assistant_msg.parts.append(
                                    ThinkingContent(content=thinking)
                                )
                                yield AgentEvent(
                                    type=AgentEventType.THINKING,
                                    content=thinking,
                                )
                                now = time.monotonic()
                                if now - _last_yield_time >= self._YIELD_INTERVAL:
                                    await asyncio.sleep(0)
                                    _last_yield_time = now

                            case ProviderEventType.TOOL_USE_START:
                                pass

                            case ProviderEventType.COMPLETE:
                                response = event.response
                                if response and response.usage:
                                    yield AgentEvent(
                                        type=AgentEventType.USAGE,
                                        usage=response.usage,
                                    )
                                    await asyncio.sleep(0)
                                    _last_yield_time = time.monotonic()
                                if response and response.tool_calls:
                                    for tc in response.tool_calls:
                                        tool_calls.append(tc)
                                        assistant_msg.parts.append(
                                            ToolCallContent(
                                                id=tc.id,
                                                name=tc.name,
                                                input=tc.get_input_dict(),
                                            )
                                        )
                                        yield AgentEvent.tool_use_with_id(
                                            tc.name, tc.id, tc.input or {}
                                        )
                                if response:
                                    assistant_msg.finished_at = int(
                                        asyncio.get_event_loop().time()
                                    )

                    if stream_failed is not None:
                        break

                    if tool_calls:
                        await self._message_service.update(assistant_msg)
                        results: list[dict[str, Any]] = []
                        async for evt in self._iter_tool_events(
                            session_id,
                            tool_calls,
                            results,
                            plan_mode=plan_mode,
                            iteration_budget=iteration_budget,
                        ):
                            yield evt

                        tool_results_msg = await self._message_service.create(
                            session_id=session_id,
                            role=MessageRole.TOOL,
                            content=json.dumps(results),
                        )
                        history.append(assistant_msg)
                        history.append(tool_results_msg)
                        try:
                            st = self._settings
                            if st and getattr(
                                st.desktop,
                                "auto_attach_desktop_screenshot",
                                False,
                            ):
                                shot_paths = _desktop_screenshot_paths_from_persisted_results(
                                    results
                                )
                                if shot_paths:
                                    attach_parts: list[ContentPart] = [
                                        TextContent(
                                            content=(
                                                "Auto-attached desktop screenshot(s) for the vision model."
                                            )
                                        )
                                    ]
                                    for sp in shot_paths:
                                        try:
                                            pp = Path(sp)
                                            if pp.is_file():
                                                attach_parts.append(
                                                    ImageContent.from_file(str(pp.resolve()))
                                                )
                                        except Exception:
                                            pass
                                    if len(attach_parts) > 1:
                                        attach_msg = await self._message_service.create(
                                            session_id=session_id,
                                            role=MessageRole.USER,
                                            parts=attach_parts,
                                        )
                                        history.append(attach_msg)
                        except Exception:
                            pass
                        history = await self._auto_compact_history(session_id, history)
                        if iteration >= self._max_iterations:
                            if self._hook_engine:
                                await self._hook_engine.fire(
                                    HookEvent.Stop,
                                    context={"session_id": session_id, "reason": "max_iterations"},
                                    provider=self._provider,
                                    working_directory=self._working_directory,
                                    suppress_agent_hooks=True,
                                )
                            await self._session_service.increment_message_count(session_id)
                            yield AgentEvent.response(assistant_msg)
                            break
                        continue

                    # --- Hook: Stop (normal completion) ---
                    await self._message_service.update(assistant_msg)
                    if self._hook_engine:
                        await self._hook_engine.fire(
                            HookEvent.Stop,
                            context={"session_id": session_id, "reason": "response_complete"},
                            provider=self._provider,
                            working_directory=self._working_directory,
                            suppress_agent_hooks=True,
                        )
                    await self._session_service.increment_message_count(session_id)
                    yield AgentEvent.response(assistant_msg)
                    break

                except Exception as e:
                    yield AgentEvent.error(f"Error in ReAct loop: {e}")
                    break
        finally:
            if (
                self._metric_memory_nudge_triggered
                or self._metric_skill_nudge_triggered
                or self._metric_memory_flush_attempts
                or self._metric_memory_flush_budget_hits
                or self._metric_memory_flush_duplicate_skips
                or self._metric_memory_reset_hits
                or self._metric_skill_reset_hits
                or self._metric_provider_bg_cache_hits
                or self._metric_provider_bg_cache_misses
                or self._metric_provider_bg_cache_resets
                or self._metric_provider_orphan_tool_healed_count
                or self._metric_provider_orphan_tool_dropped_count
            ):
                _logger.info(
                    "closed-loop-metrics session=%s memory_nudge=%s skill_nudge=%s flush=%s/%s flush_budget_hit=%s flush_dup_skip=%s reset(memory=%s,skill=%s) bg_cache(hit=%s,miss=%s,reset=%s) orphan(heal=%s,drop=%s)",
                    session_id,
                    self._metric_memory_nudge_triggered,
                    self._metric_skill_nudge_triggered,
                    self._metric_memory_flush_success,
                    self._metric_memory_flush_attempts,
                    self._metric_memory_flush_budget_hits,
                    self._metric_memory_flush_duplicate_skips,
                    self._metric_memory_reset_hits,
                    self._metric_skill_reset_hits,
                    self._metric_provider_bg_cache_hits,
                    self._metric_provider_bg_cache_misses,
                    self._metric_provider_bg_cache_resets,
                    self._metric_provider_orphan_tool_healed_count,
                    self._metric_provider_orphan_tool_dropped_count,
                )
                emit_ops_event(
                    "agent_closed_loop_metrics",
                    {
                        "session_id": session_id,
                        "domain": "general",
                        "source": "agent",
                        "tool_name": "memory",
                        "memory_nudge": self._metric_memory_nudge_triggered,
                        "skill_nudge": self._metric_skill_nudge_triggered,
                        "flush_success": self._metric_memory_flush_success,
                        "flush_attempts": self._metric_memory_flush_attempts,
                        "flush_budget_hit": self._metric_memory_flush_budget_hits,
                        "flush_dup_skip": self._metric_memory_flush_duplicate_skips,
                        "provider_bg_cache_hits": self._metric_provider_bg_cache_hits,
                        "provider_bg_cache_misses": self._metric_provider_bg_cache_misses,
                        "provider_bg_cache_resets": self._metric_provider_bg_cache_resets,
                        "provider_orphan_tool_healed_count": self._metric_provider_orphan_tool_healed_count,
                        "provider_orphan_tool_dropped_count": self._metric_provider_orphan_tool_dropped_count,
                    },
                )
            self._ephemeral_user_suffix = ""
            self._ephemeral_user_target_id = None
            # --- Hook: SessionEnd ---
            if self._hook_engine:
                try:
                    await self._hook_engine.fire(
                        HookEvent.SessionEnd,
                        context={"session_id": session_id, "reason": "completed"},
                        provider=self._provider,
                        working_directory=self._working_directory,
                        suppress_agent_hooks=True,
                    )
                except Exception:
                    pass
            self._active_requests.pop(session_id, None)

    _READ_ONLY_TOOLS = frozenset({
        "view", "ls", "glob", "grep", "diagnostics",
        "search", "batch_view", "rg",
    })

    def _should_parallelize_tool_calls(self, tool_calls: list[ToolCall]) -> bool:
        """True when parallel gather is allowed for this batch of tool calls.

        Parallelizable scenarios:
        1. All read-only tools (no permission modal needed)
        2. All AgentTool/subagent calls (independent sub-tasks)
        3. Tools with session-scoped permission pre-approval (skip serial modal)
        4. Mixed read-only + subagent calls (when no permission_client)

        Streaming tools always force serial execution.
        Mixed AgentTool + non-parallelizable non-subagent tools force serial.
        """
        if len(tool_calls) < 2:
            return False
        st = self._settings
        if st is None or not bool(getattr(st, "parallel_tool_calls", False)):
            return False
        from .tools.subagent import AgentTool

        has_subagent = False
        has_streaming = False
        has_non_parallelizable = False

        for tc in tool_calls:
            t = self._tools.get(tc.name)
            if t is None:
                return False
            if isinstance(t, AgentTool):
                has_subagent = True
                continue
            if hasattr(t, "run_stream") and callable(getattr(t, "run_stream")):
                has_streaming = True
                continue
            if self._permission_client is not None and tc.name not in self._READ_ONLY_TOOLS:
                if not self._is_session_pre_approved(tc.name):
                    has_non_parallelizable = True

        if has_streaming:
            return False

        if has_subagent and has_non_parallelizable:
            return False

        if has_subagent:
            return True

        if has_non_parallelizable:
            return False

        return True

    def _is_session_pre_approved(self, tool_name: str) -> bool:
        if self._permission_client is None:
            return False
        try:
            session_perms = getattr(
                self._permission_client, "_session_permissions", None
            )
            if session_perms and tool_name in session_perms:
                return True
        except Exception:
            pass
        return False

    async def _iter_tool_events(
        self,
        session_id: str,
        tool_calls: list[ToolCall],
        results: list[dict[str, Any]],
        *,
        plan_mode: bool = False,
        iteration_budget: IterationBudget | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Execute tool calls (optionally streaming) and yield UI events.

        Args:
            session_id: Session ID
            tool_calls: Tool calls to execute
            results: list to append persisted tool results into

        Yields:
            AgentEvent instances during tool execution
        """
        if self._should_parallelize_tool_calls(tool_calls):

            from .tools.subagent import AgentTool as _AT

            async def _run_one(
                idx: int,
                tc: ToolCall,
            ) -> tuple[int, list[AgentEvent], list[dict[str, Any]]]:
                t = self._tools.get(tc.name)
                sem = (
                    self._subagent_semaphore
                    if isinstance(t, _AT)
                    else self._tool_semaphore
                )
                frag: list[dict[str, Any]] = []
                buf: list[AgentEvent] = []
                async with sem:
                    async for evt in self._collect_single_tool_events(
                        session_id,
                        tc,
                        frag,
                        plan_mode=plan_mode,
                        iteration_budget=iteration_budget,
                    ):
                        buf.append(evt)
                return (idx, buf, frag)

            gathered = await asyncio.gather(
                *(_run_one(i, tc) for i, tc in enumerate(tool_calls))
            )
            for _idx, ev_buf, frag in sorted(gathered, key=lambda p: p[0]):
                for evt in ev_buf:
                    yield evt
                results.extend(frag)
            return

        for tool_call in tool_calls:
            async for evt in self._collect_single_tool_events(
                session_id,
                tool_call,
                results,
                plan_mode=plan_mode,
                iteration_budget=iteration_budget,
            ):
                yield evt

    async def _collect_single_tool_events(
        self,
        session_id: str,
        tool_call: ToolCall,
        results_fragment: list[dict[str, Any]],
        *,
        plan_mode: bool = False,
        iteration_budget: IterationBudget | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one tool call; append persisted dicts to results_fragment."""
        tool_name = tool_call.name

        tool = self._tools.get(tool_name)
        if not tool:
            err = f"Error: Unknown tool '{tool_name}'"
            results_fragment.append(_persisted_tool_result_dict(tool_call, err, True))
            yield AgentEvent.tool_result(tool_name, tool_call.id, err, True, True)
            return

        from .tools import ToolContext
        _base_tool_timeout = 120
        if self._settings is not None:
            _base_tool_timeout = int(getattr(self._settings, "tool_timeout_seconds", 120))
        TOOL_TIMEOUT = _base_tool_timeout  # per-tool hard timeout (seconds)

        # Dynamic timeout for write tool based on content size
        if tool_name == "write":
            _write_params = tool_call.get_input_dict()
            _content_len = len(_write_params.get("content", ""))
            # +5s base + 20s per 100KB (more generous to account for disk I/O variance)
            TOOL_TIMEOUT = max(TOOL_TIMEOUT, 10) + (_content_len // 100_000) * 20

        context = ToolContext(
            session_id=session_id,
            message_id="",
            working_directory=self._working_directory,
            permission_service=self._permission_client,
            plan_mode=plan_mode,
            iteration_budget=iteration_budget,
        )

        try:
            self._on_tool_used(tool_name)
            if plan_mode:
                allowed, reason = is_tool_allowed_in_plan_mode(
                    tool_name,
                    tool_call.get_input_dict(),
                )
                if not allowed:
                    _err = reason or "Tool is blocked in /plan mode."
                    results_fragment.append(_persisted_tool_result_dict(tool_call, _err, True))
                    yield AgentEvent.tool_result(tool_name, tool_call.id, _err, True, True)
                    return

            # Use _coerce_tool_params for robust parameter extraction before validation
            from .tools.advanced import _coerce_tool_params
            _coerced_params = _coerce_tool_params(tool_call)
            if not _coerced_params:
                # Fallback to get_input_dict if _coerce_tool_params returns empty
                _coerced_params = tool_call.get_input_dict()
            # Feed coerced params back for write/edit tools so their run()
            # method receives already-normalized input (avoids re-parsing
            # malformed JSON from models like GLM).
            if tool_name in ("write", "edit"):
                tool_call.input = _coerced_params

            _pilot_err = pilot_validate_tool_input(
                tool_name, _coerced_params
            )
            if _pilot_err:
                results_fragment.append(
                    _persisted_tool_result_dict(tool_call, _pilot_err, True)
                )
                yield AgentEvent.tool_result(
                    tool_name, tool_call.id, _pilot_err, True, True
                )
                return

            # --- Hook: PreToolUse (can deny the tool call) ---
            if self._hook_engine:
                _decisions = await self._hook_engine.fire(
                    HookEvent.PreToolUse,
                    match_value=tool_name,
                    context={
                        "session_id": session_id,
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_name,
                        "tool_input": tool_call.get_input_dict(),
                    },
                    provider=self._provider,
                    working_directory=self._working_directory,
                    suppress_agent_hooks=True,
                )
                if any(d.permissionDecision == "deny" for d in _decisions):
                    _reason = next(
                        (d.permissionDecisionReason for d in _decisions if d.permissionDecision == "deny"),
                        "Blocked by hook",
                    )
                    _err = f"Permission denied by hook: {_reason}"
                    results_fragment.append(_persisted_tool_result_dict(tool_call, _err, True))
                    yield AgentEvent.tool_result(tool_name, tool_call.id, _err, True, True)
                    return

            # Read-only tool cache: avoid redundant calls within a single Agent run
            if tool_name in self._READ_ONLY_TOOLS:
                _cache_key = f"{tool_name}:{json.dumps(tool_call.get_input_dict(), sort_keys=True, ensure_ascii=False)}"
                _cached = self._tool_result_cache.get(_cache_key)
                if _cached is not None:
                    _clean_resp = sanitize_text(_cached.content or "")
                    _clean_resp = self._maybe_save_artifact(session_id, tool_call.id, _clean_resp)
                    results_fragment.append(
                        _persisted_tool_result_dict(tool_call, _clean_resp, _cached.is_error)
                    )
                    yield AgentEvent.tool_result(
                        tool_name, tool_call.id, _clean_resp, _cached.is_error, True
                    )
                    return

            # Learning observations: lightweight local telemetry for /learn.
            try:
                provider_name = getattr(self._provider, "name", "") or self._provider.__class__.__name__
                model_name = str(getattr(self._provider, "model", "") or "")
                reasoning_effort = str(getattr(self._provider, "reasoning_effort", "") or "")
                record_tool_observation_async(
                    self._settings,
                    phase="tool_start",
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=tool_call.id,
                    tool_input=tool_call.get_input_dict(),
                    tool_output="",
                    is_error=False,
                    source_provider=str(provider_name),
                    source_model=model_name,
                    reasoning_effort=reasoning_effort,
                )
            except Exception:
                pass

            # Sub-agent: stream nested TOOL_USE / TOOL_RESULT to TUI (hud_only), then final result.
            from .tools.subagent import AgentTool, SubagentRunFinal

            if isinstance(tool, AgentTool):
                final: SubagentRunFinal | None = None
                _last_sub_yield = time.monotonic()
                try:
                    async for item in tool.forward_subagent_events(tool_call, context):
                        if isinstance(item, SubagentRunFinal):
                            final = item
                        else:
                            yield item
                        now = time.monotonic()
                        if now - _last_sub_yield >= self._YIELD_INTERVAL:
                            await asyncio.sleep(0)
                            _last_sub_yield = now
                except Exception as e:
                    err = f"Error executing tool: {e}"
                    results_fragment.append(_persisted_tool_result_dict(tool_call, err, True))
                    yield AgentEvent.tool_result(tool_name, tool_call.id, err, True, True)
                    await asyncio.sleep(0)
                    return

                if final is None:
                    err = "Error: sub-agent produced no result"
                    results_fragment.append(_persisted_tool_result_dict(tool_call, err, True))
                    yield AgentEvent.tool_result(tool_name, tool_call.id, err, True, True)
                    await asyncio.sleep(0)
                    return

                response = final.response
                _clean_resp = sanitize_text(response.content or "")
                _clean_resp = self._maybe_save_artifact(session_id, tool_call.id, _clean_resp)
                results_fragment.append(
                    _persisted_tool_result_dict(
                        tool_call, _clean_resp, response.is_error
                    )
                )
                yield AgentEvent.tool_result(
                    tool_name,
                    tool_call.id,
                    _clean_resp,
                    response.is_error,
                    True,
                )
                if self._hook_engine:
                    _post_event = (
                        HookEvent.PostToolUseFailure
                        if response.is_error
                        else HookEvent.PostToolUse
                    )
                    await self._hook_engine.fire(
                        _post_event,
                        match_value=tool_name,
                        context={
                            "session_id": session_id,
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_name,
                            "tool_input": tool_call.get_input_dict(),
                            "tool_output": response.content,
                        },
                        provider=self._provider,
                        working_directory=self._working_directory,
                        suppress_agent_hooks=True,
                    )
                try:
                    provider_name = getattr(self._provider, "name", "") or self._provider.__class__.__name__
                    model_name = str(getattr(self._provider, "model", "") or "")
                    reasoning_effort = str(getattr(self._provider, "reasoning_effort", "") or "")
                    record_tool_observation_async(
                        self._settings,
                        phase="tool_complete",
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=tool_call.id,
                        tool_input=tool_call.get_input_dict(),
                        tool_output=response.content,
                        is_error=bool(response.is_error),
                        source_provider=str(provider_name),
                        source_model=model_name,
                        reasoning_effort=reasoning_effort,
                    )
                except Exception:
                    pass
                await asyncio.sleep(0)
                return

            # Optional streaming path (e.g., bash stdout)
            if hasattr(tool, "run_stream") and callable(getattr(tool, "run_stream")):
                final_response = None
                final_meta = ""
                async for partial in tool.run_stream(tool_call, context):  # type: ignore[attr-defined]
                    meta = (partial.metadata or "").lower()
                    if meta.startswith("final"):
                        final_response = partial
                        final_meta = meta
                        break
                    # stream chunk
                    if partial.content:
                        stream = meta if meta in ("stdout", "stderr") else None
                        yield AgentEvent.tool_result(
                            tool_name,
                            tool_call.id,
                            partial.content,
                            False,
                            False,
                            tool_stream=stream,
                        )
                        await asyncio.sleep(0)

                if final_response is None:
                    # Fallback if stream didn't provide final marker
                    final_response = await tool.run(tool_call, context)

                _clean_content = sanitize_text(final_response.content or "")
                _clean_content = self._maybe_save_artifact(session_id, tool_call.id, _clean_content)
                results_fragment.append(
                    _persisted_tool_result_dict(
                        tool_call, _clean_content, final_response.is_error
                    )
                )
                # Parse final meta: "final:<code>:<elapsed>" or "final:timeout"
                rc: int | None = None
                elapsed: float | None = None
                timeout_flag = False
                try:
                    parts = (final_meta or "").split(":")
                    if len(parts) >= 2 and parts[1] == "timeout":
                        timeout_flag = True
                    elif len(parts) >= 3:
                        rc = int(parts[1])
                        elapsed = float(parts[2])
                except Exception:
                    pass
                yield AgentEvent.tool_result(
                    tool_name,
                    tool_call.id,
                    "",
                    bool(final_response.is_error),
                    True,
                    tool_returncode=rc,
                    tool_elapsed=elapsed,
                    tool_timeout=timeout_flag,
                )
                # --- Hook: PostToolUse / PostToolUseFailure (streaming) ---
                if self._hook_engine:
                    _post_event = (
                        HookEvent.PostToolUseFailure
                        if final_response.is_error or timeout_flag
                        else HookEvent.PostToolUse
                    )
                    await self._hook_engine.fire(
                        _post_event,
                        match_value=tool_name,
                        context={
                            "session_id": session_id,
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_name,
                            "tool_input": tool_call.get_input_dict(),
                            "tool_output": final_response.content,
                            "tool_returncode": rc,
                            "tool_elapsed": elapsed,
                        },
                        provider=self._provider,
                        working_directory=self._working_directory,
                        suppress_agent_hooks=True,
                    )
                try:
                    provider_name = getattr(self._provider, "name", "") or self._provider.__class__.__name__
                    model_name = str(getattr(self._provider, "model", "") or "")
                    reasoning_effort = str(getattr(self._provider, "reasoning_effort", "") or "")
                    record_tool_observation_async(
                        self._settings,
                        phase="tool_complete",
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=tool_call.id,
                        tool_input=tool_call.get_input_dict(),
                        tool_output=final_response.content,
                        is_error=bool(final_response.is_error or timeout_flag),
                        source_provider=str(provider_name),
                        source_model=model_name,
                        reasoning_effort=reasoning_effort,
                    )
                except Exception:
                    pass
            else:
                from .tools.subagent import AgentTool as _AgentToolCheck
                _effective_timeout = TOOL_TIMEOUT
                if isinstance(tool, _AgentToolCheck):
                    _params = tool_call.input if isinstance(tool_call.input, dict) else {}
                    _effective_timeout = min(int(_params.get("timeout", 300)), 600)
                try:
                    response = await asyncio.wait_for(
                        tool.run(tool_call, context),
                        timeout=_effective_timeout,
                    )
                except asyncio.TimeoutError:
                    _timeout_msg = f"Tool '{tool_name}' timed out after {_effective_timeout}s"
                    results_fragment.append(
                        _persisted_tool_result_dict(tool_call, _timeout_msg, True)
                    )
                    yield AgentEvent.tool_result(tool_name, tool_call.id, _timeout_msg, True, True, tool_timeout=True)
                    return
                _clean_resp = sanitize_text(response.content or "")
                _clean_resp = self._maybe_save_artifact(session_id, tool_call.id, _clean_resp)
                results_fragment.append(
                    _persisted_tool_result_dict(
                        tool_call, _clean_resp, response.is_error
                    )
                )
                yield AgentEvent.tool_result(
                    tool_name,
                    tool_call.id,
                    _clean_resp,
                    response.is_error,
                    True,
                )
                # Cache successful read-only tool results
                if tool_name in self._READ_ONLY_TOOLS and not response.is_error:
                    self._tool_result_cache[_cache_key] = response
                # --- Hook: PostToolUse / PostToolUseFailure (non-streaming) ---
                if self._hook_engine:
                    _post_event = (
                        HookEvent.PostToolUseFailure if response.is_error else HookEvent.PostToolUse
                    )
                    await self._hook_engine.fire(
                        _post_event,
                        match_value=tool_name,
                        context={
                            "session_id": session_id,
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_name,
                            "tool_input": tool_call.get_input_dict(),
                            "tool_output": response.content,
                        },
                        provider=self._provider,
                        working_directory=self._working_directory,
                        suppress_agent_hooks=True,
                    )
                try:
                    provider_name = getattr(self._provider, "name", "") or self._provider.__class__.__name__
                    model_name = str(getattr(self._provider, "model", "") or "")
                    reasoning_effort = str(getattr(self._provider, "reasoning_effort", "") or "")
                    record_tool_observation_async(
                        self._settings,
                        phase="tool_complete",
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=tool_call.id,
                        tool_input=tool_call.get_input_dict(),
                        tool_output=response.content,
                        is_error=bool(response.is_error),
                        source_provider=str(provider_name),
                        source_model=model_name,
                        reasoning_effort=reasoning_effort,
                    )
                except Exception:
                    pass
            await asyncio.sleep(0)
        except Exception as e:
            err = f"Error executing tool: {e}"
            results_fragment.append(_persisted_tool_result_dict(tool_call, err, True))
            yield AgentEvent.tool_result(tool_name, tool_call.id, err, True, True)
            await asyncio.sleep(0)


    async def _create_user_message(
        self,
        session_id: str,
        content: str,
        attachments: list[Any] | None = None,
    ) -> Message:
        parts: list[ContentPart] = []

        if content:
            parts.append(TextContent(content=content))

        if attachments:
            inline_parts: list[str] = []
            for attachment in attachments:
                file_path = getattr(attachment, "path", "")
                file_name = getattr(attachment, "name", "") or Path(file_path).name
                is_image = getattr(attachment, "is_image", False)

                if is_image:
                    try:
                        image_content = ImageContent.from_file(file_path)
                        parts.append(image_content)
                        inline_parts.append(f"\n[Image: {file_name}]\n")
                    except Exception:
                        inline_parts.append(f"\n[Image: {file_name} (failed to load)]\n")
                else:
                    try:
                        p = Path(file_path)
                        if p.is_file():
                            size = p.stat().st_size
                            try:
                                text_content = p.read_text(encoding="utf-8")
                                preview = text_content[:8000]
                                truncated = "..." if len(text_content) > 8000 else ""
                                inline_parts.append(
                                    f"\n[File: {file_name} ({size} bytes)]\n{preview}{truncated}\n"
                                )
                            except UnicodeDecodeError:
                                inline_parts.append(
                                    f"\n[File: {file_name} ({size} bytes, binary)]\n"
                                )
                    except Exception:
                        inline_parts.append(f"\n[File: {file_name}]\n")

            if inline_parts:
                parts.append(TextContent(content="".join(inline_parts)))

        return await self._message_service.create(
            session_id=session_id,
            role=MessageRole.USER,
            parts=parts,
        )

    def _convert_history_to_provider(
        self,
        history: list[Message],
        *,
        tools_present: bool = False,
        use_incremental_cache: bool = True,
        cache_scope: Literal["main", "background"] = "main",
        cache_session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert message history to provider format with multimodal support.

        Uses incremental conversion: only processes new messages since the last call,
        appending them to an internal cache for O(1) amortized per-iteration cost.

        Args:
            history: Message history

        Returns:
            Provider format messages
        """
        if not hasattr(self, "_provider_messages_cache"):
            self._provider_messages_cache = []
            self._provider_messages_cache_len = 0
        if not hasattr(self, "_bg_provider_messages_cache"):
            self._bg_provider_messages_cache = []
            self._bg_provider_messages_cache_len = 0
            self._bg_provider_messages_cache_session_id = None
        if not hasattr(self, "_metric_provider_bg_cache_hits"):
            self._metric_provider_bg_cache_hits = 0
            self._metric_provider_bg_cache_misses = 0
            self._metric_provider_bg_cache_resets = 0
            self._metric_provider_normalize_full_fallbacks = 0
            self._metric_provider_orphan_tool_healed_count = 0
            self._metric_provider_orphan_tool_dropped_count = 0

        # Optional uncached mode for one-shot conversions.
        if not use_incremental_cache:
            cache = []
            cache_len = 0
        elif cache_scope == "background":
            if (
                cache_session_id
                and self._bg_provider_messages_cache_session_id != cache_session_id
            ):
                self._bg_provider_messages_cache = []
                self._bg_provider_messages_cache_len = 0
                self._bg_provider_messages_cache_session_id = cache_session_id
                self._metric_provider_bg_cache_resets += 1
            cache = self._bg_provider_messages_cache
            cache_len = int(self._bg_provider_messages_cache_len)
        else:
            cache = self._provider_messages_cache
            cache_len = int(self._provider_messages_cache_len)

        new_count = len(history) - cache_len
        if new_count < 0:
            cache.clear()
            cache_len = 0
            if use_incremental_cache:
                if cache_scope == "background":
                    self._bg_provider_messages_cache_len = 0
                    self._metric_provider_bg_cache_resets += 1
                else:
                    self._provider_messages_cache_len = 0
            new_count = len(history)

        inject_reasoning = False
        try:
            fn = getattr(self._provider, "should_inject_reasoning_history", None)
            if callable(fn):
                inject_reasoning = bool(fn(tools_present=tools_present))
        except Exception:
            inject_reasoning = False

        if new_count == 0 and cache:
            if use_incremental_cache and cache_scope == "background":
                self._metric_provider_bg_cache_hits += 1
            result = list(cache)
            if not inject_reasoning:
                for row in result:
                    row.pop("reasoning_content", None)
            return result
        if use_incremental_cache and cache_scope == "background":
            self._metric_provider_bg_cache_misses += 1

        if not cache:
            system_msg = {"role": "system", "content": self._system_prompt}
            cache.append(system_msg)

        old_provider_rows = len(cache)
        new_msgs = history[cache_len:]
        for msg in new_msgs:
            converted = self._convert_single_message(msg, inject_reasoning, cache=cache)
            if converted is not None:
                cache.extend(converted)
        if use_incremental_cache:
            if cache_scope == "background":
                self._bg_provider_messages_cache_len = len(history)
                if cache_session_id:
                    self._bg_provider_messages_cache_session_id = cache_session_id
            else:
                self._provider_messages_cache_len = len(history)

        result = list(cache)
        if not inject_reasoning:
            for row in result:
                row.pop("reasoning_content", None)
        # Incremental normalize: find the last assistant with tool_calls in the
        # *old* part of the cache.  Only new messages (and the boundary assistant)
        # need rescanning — everything before that point was already correct.
        if new_count > 0 and old_provider_rows > 1:
            normalize_start = 0
            for idx in range(old_provider_rows - 1, -1, -1):
                if result[idx].get("role") == "assistant" and result[idx].get("tool_calls"):
                    normalize_start = idx
                    break
            _normalize_tool_message_sequences_for_api(result, start_from=normalize_start)
        else:
            self._metric_provider_normalize_full_fallbacks += 1
            _normalize_tool_message_sequences_for_api(result, start_from=0)
        return result

    def _convert_single_message(
        self,
        msg: Message,
        inject_reasoning: bool,
        *,
        cache: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if msg.role == MessageRole.TOOL:
            raw = (msg.content or "").strip()
            try:
                batch = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                batch = []
            if isinstance(batch, list) and batch:
                tool_rows: list[dict[str, Any]] = []
                oai_tool_calls: list[dict[str, Any]] = []
                for idx, item in enumerate(batch):
                    if not isinstance(item, dict):
                        continue
                    tid = (
                        item.get("tool_call_id")
                        or item.get("tool_use_id")
                        or ""
                    )
                    if not tid:
                        tid = f"clawcode_missing_tool_call_id_{idx}"
                    name = item.get("name") or item.get("tool_name") or "unknown"
                    args_raw = item.get("arguments")
                    if isinstance(args_raw, str):
                        arg_str = args_raw
                    elif isinstance(args_raw, dict):
                        arg_str = json.dumps(args_raw, ensure_ascii=False)
                    else:
                        arg_str = "{}"
                    oai_tool_calls.append({
                        "id": tid,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arg_str,
                        },
                    })
                    body = item.get("content", "")
                    if not isinstance(body, str):
                        body = json.dumps(body, ensure_ascii=False)
                    if item.get("is_error"):
                        body = f"Error: {body}" if body else "Error"
                    tool_rows.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": body,
                    })
                # Attach tool_calls to preceding assistant if needed.
                i = len(cache) - 1
                while i >= 0 and cache[i].get("role") == "tool":
                    i -= 1
                can_emit_tools = False
                if i >= 0 and cache[i].get("role") == "assistant":
                    if not cache[i].get("tool_calls") and oai_tool_calls:
                        cache[i]["tool_calls"] = oai_tool_calls
                        if cache[i].get("content") is None:
                            cache[i]["content"] = ""
                        can_emit_tools = True
                    elif cache[i].get("tool_calls"):
                        can_emit_tools = True
                if can_emit_tools and tool_rows:
                    return tool_rows
                elif tool_rows and not can_emit_tools:
                    _logger.warning(
                        "Dropped orphan tool results (no preceding assistant with tool_calls)"
                    )
            elif raw:
                _logger.warning(
                    "Skipping non-JSON tool message (would break strict OpenAI/DeepSeek APIs)"
                )
            return []

        if msg.role == MessageRole.ASSISTANT and msg.tool_calls():
            text_blocks: list[str] = []
            for p in msg.parts:
                if isinstance(p, TextContent):
                    text_blocks.append(sanitize_text(p.content or ""))
            combined = "\n".join(x for x in text_blocks if x).strip()
            oai_tool_calls: list[dict[str, Any]] = []
            for tc in msg.tool_calls():
                arg = tc.input
                if isinstance(arg, dict):
                    arg_str = json.dumps(arg, ensure_ascii=False)
                else:
                    arg_str = str(arg) if arg else "{}"
                oai_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": arg_str,
                    },
                })
            row = {
                "role": "assistant",
                "content": combined or "",
                "tool_calls": oai_tool_calls,
            }
            if inject_reasoning and msg.thinking:
                row["reasoning_content"] = msg.thinking
            return [row]

        has_images = any(isinstance(p, ImageContent) for p in msg.parts)
        has_files = any(isinstance(p, FileContent) for p in msg.parts)

        if has_images or has_files:
            content_parts = []
            for part in msg.parts:
                if isinstance(part, TextContent):
                    content_parts.append({
                        "type": "text",
                        "content": sanitize_text(part.content or ""),
                    })
                elif isinstance(part, ImageContent):
                    content_parts.append(part.to_dict())
                elif isinstance(part, FileContent):
                    content_parts.append(part.to_dict())
                elif isinstance(part, ThinkingContent):
                    content_parts.append({
                        "type": "text",
                        "content": f"[Thinking] {part.content}",
                    })
                else:
                    content_parts.append({
                        "type": "text",
                        "content": str(part.to_dict()),
                    })
            provider_msg: dict[str, Any] = {
                "role": msg.role.value,
                "content": content_parts,
            }
            if msg.role == MessageRole.ASSISTANT and inject_reasoning and msg.thinking:
                provider_msg["reasoning_content"] = msg.thinking
        else:
            provider_msg = {
                "role": msg.role.value,
                "content": sanitize_text(msg.content or ""),
            }
            if (
                msg.role == MessageRole.USER
                and self._ephemeral_user_suffix
                and self._ephemeral_user_target_id
                and msg.id == self._ephemeral_user_target_id
            ):
                provider_msg["content"] = (provider_msg["content"] + self._ephemeral_user_suffix).strip()
            if msg.role == MessageRole.ASSISTANT and inject_reasoning and msg.thinking:
                provider_msg["reasoning_content"] = msg.thinking

        return [provider_msg]


__all__ = [
    "Agent",
    "AgentEvent",
    "AgentEventType",
]
