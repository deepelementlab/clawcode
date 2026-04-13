"""Subagent support aligned with Claude Code (Agent / Task tool, .claude/agents/)."""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, TYPE_CHECKING

from .base import BaseTool, ToolInfo, ToolCall, ToolResponse, ToolContext
from ..claw_support.iteration_budget import IterationBudget
from ...agents.loader import load_merged_agent_definitions
from ...llm.plan_policy import PLAN_ALLOWED_SUBAGENTS, filter_read_only_tools
from ...message import ContentPart, Message, MessageRole
from ...plugin.types import HookEvent
from ...utils.text import sanitize_text

if TYPE_CHECKING:
    from ...plugin.hooks import HookEngine
    from ..agent import AgentEvent

else:
    HookEngine = Any  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


class _SubAgentMemoryMessageService:
    """Minimal in-memory message store for nested Agent (no DB)."""

    def __init__(self) -> None:
        self._by_session: dict[str, list[Message]] = {}

    async def list_by_session(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        msgs = self._by_session.get(session_id, [])
        return msgs[offset : offset + limit]

    async def create(
        self,
        session_id: str,
        role: MessageRole,
        content: str = "",
        parts: list[ContentPart] | None = None,
        model: str | None = None,
    ) -> Message:
        msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            parts=list(parts or []),
            model=model,
        )
        if content:
            msg.content = content
        self._by_session.setdefault(session_id, []).append(msg)
        return msg

    async def update(self, message: Message) -> Message:
        message.updated_at = int(time.time())
        return message


class _SubAgentMemorySessionService:
    """Minimal session service for nested Agent (increments are no-ops)."""

    async def increment_message_count(self, session_id: str) -> None:
        return None


# Claude Code tool names -> ClawCode internal tool names (None = unsupported / delegate)
CLAUDE_TO_CLAW_TOOL: dict[str, str | None] = {
    "Read": "view",
    "Write": "write",
    "Edit": "edit",
    "Glob": "glob",
    "Grep": "grep",
    "Bash": "bash",
    "WebFetch": "fetch",
    "Diagnostics": "diagnostics",
    "LSP": "diagnostics",
    "Agent": None,
    "Task": None,
    "ListMcpResourcesTool": "mcp_call",
    "ReadMcpResourceTool": "mcp_call",
    "mcp_call": "mcp_call",
    "sourcegraph": "sourcegraph",
    "Sourcegraph": "sourcegraph",
    "ls": "ls",
    "view": "view",
    "write": "write",
    "edit": "edit",
    "patch": "patch",
    "fetch": "fetch",
    "TodoWrite": "TodoWrite",
    "TodoRead": "TodoRead",
    "UpdateProjectState": "UpdateProjectState",
}

DELEGATE_TOOL_NAMES = frozenset({"Agent", "Task", "agent"})


def _claude_name_to_claw(name: str) -> str | None:
    key = name.strip()
    if key in CLAUDE_TO_CLAW_TOOL:
        return CLAUDE_TO_CLAW_TOOL[key]
    kl = key.lower()
    if kl in CLAUDE_TO_CLAW_TOOL:
        return CLAUDE_TO_CLAW_TOOL[kl]
    return kl if kl else None


def normalize_claude_tool_list(names: list[str]) -> list[str]:
    out: list[str] = []
    for raw in names:
        mapped = _claude_name_to_claw(raw)
        if mapped:
            out.append(mapped)
    return sorted(set(out))


def filter_delegate_tools(tools: list[BaseTool]) -> list[BaseTool]:
    """Strip Agent/Task so subagents cannot nest delegation."""
    return [t for t in tools if t and t.info().name not in DELEGATE_TOOL_NAMES]


def compute_allowed_internal_tools(
    available: list[BaseTool],
    claude_allowlist: list[str] | None,
    claude_disallowlist: list[str],
) -> list[str]:
    internal_available = [t.info().name for t in available if t]
    disallow = set(normalize_claude_tool_list(claude_disallowlist))
    if claude_allowlist is None:
        names = [n for n in internal_available if n not in DELEGATE_TOOL_NAMES]
    else:
        allowed = set(normalize_claude_tool_list(claude_allowlist))
        names = [n for n in internal_available if n in allowed]
    names = [n for n in names if n not in disallow and n not in DELEGATE_TOOL_NAMES]
    return names


class SubAgentEventType(str, Enum):
    """Events emitted during subagent execution."""

    START = "start"
    progress = "progress"
    tool_call = "tool_call"
    tool_result = "tool_result"
    complete = "complete"
    error = "error"


class SubAgentType(str, Enum):
    """Logical subagent kinds (hooks / logging)."""

    EXPLORE = "explore"
    CODER = "coder"
    TASK = "task"
    PLAN = "plan"
    TEST = "test"
    REVIEW = "review"
    CUSTOM = "custom"
    GENERAL_PURPOSE = "general-purpose"
    CLAUDE_CODE_GUIDE = "claude-code-guide"


SUBAGENT_BUILTIN_TYPES: dict[str, SubAgentType] = {
    "explore": SubAgentType.EXPLORE,
    "plan": SubAgentType.PLAN,
    "code-review": SubAgentType.REVIEW,
    "general-purpose": SubAgentType.GENERAL_PURPOSE,
}


def get_builtin_subagent_type(subagent_type: str) -> SubAgentType | None:
    return SUBAGENT_BUILTIN_TYPES.get(subagent_type)


READ_ONLY_TOOLS = {"view", "ls", "glob", "grep", "diagnostics", "bash"}
# Coder tools include dangerous local execution/scheduling entrypoints.
CODER_TOOLS = {
    "view",
    "ls",
    "glob",
    "grep",
    "diagnostics",
    "bash",
    "write",
    "edit",
    "execute_code",
    "cronjob",
}
PLAN_TOOLS = set(READ_ONLY_TOOLS)
TEST_TOOLS = set(READ_ONLY_TOOLS)
REVIEW_TOOLS = {"view", "ls", "glob", "grep", "diagnostics"}

DEFAULT_MAX_ITERATIONS = 20
DEFAULT_TIMEOUT_MS = 300000


class IsolationMode(str, Enum):
    NONE = "none"
    WORKTREE = "worktree"
    SANDBOX = "sandbox"
    CONTAINER = "container"
    FORK = "fork"


DEFAULT_ISOLATION_MODE = IsolationMode.FORK


@dataclass
class SubAgentContext:
    task: str = ""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4().hex[:8]))
    parent_session_id: str | None = None
    working_directory: str = ""
    allowed_tools: list[str] = field(default_factory=lambda: list(READ_ONLY_TOOLS))
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    isolation_mode: IsolationMode = field(default=DEFAULT_ISOLATION_MODE)
    subagent_type: SubAgentType = field(default=SubAgentType.TASK)
    agent_key: str = ""
    custom_system_prompt: str | None = None
    subagent_model: str | None = None
    model: str | None = None
    provider_key: str | None = None
    user_invocable: bool = True
    #: Parent Claw shared cap; inner :class:`~clawcode.llm.agent.Agent.run` consumes the same pool.
    iteration_budget: IterationBudget | None = None

    def is_read_only(self) -> bool:
        return self.isolation_mode in (IsolationMode.NONE, IsolationMode.FORK)

    def is_isolation_mode(self) -> bool:
        return self.isolation_mode in (
            IsolationMode.WORKTREE,
            IsolationMode.SANDBOX,
            IsolationMode.CONTAINER,
        )

    def supports_resume(self) -> bool:
        return self.isolation_mode == IsolationMode.WORKTREE

    def get_tool_subset(self) -> list[str]:
        if self.subagent_type == SubAgentType.CODER:
            return list(CODER_TOOLS)
        if self.subagent_type == SubAgentType.PLAN:
            return list(PLAN_TOOLS)
        if self.subagent_type == SubAgentType.TEST:
            return list(TEST_TOOLS)
        if self.subagent_type == SubAgentType.REVIEW:
            return list(REVIEW_TOOLS)
        return list(READ_ONLY_TOOLS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "working_directory": self.working_directory,
            "allowed_tools": self.allowed_tools,
            "max_iterations": self.max_iterations,
            "timeout_ms": self.timeout_ms,
            "isolation_mode": self.isolation_mode.value,
            "subagent_type": self.subagent_type.value,
            "agent_key": self.agent_key,
            "model": self.model,
            "provider_key": self.provider_key,
            "user_invocable": self.user_invocable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubAgentContext:
        return cls(
            task=data.get("task", ""),
            session_id=data.get("session_id", str(uuid.uuid4().hex[:8])),
            parent_session_id=data.get("parent_session_id"),
            working_directory=data.get("working_directory", ""),
            allowed_tools=data.get("allowed_tools", list(READ_ONLY_TOOLS)),
            max_iterations=data.get("max_iterations", DEFAULT_MAX_ITERATIONS),
            timeout_ms=data.get("timeout_ms", DEFAULT_TIMEOUT_MS),
            isolation_mode=IsolationMode(data.get("isolation_mode", DEFAULT_ISOLATION_MODE.value)),
            subagent_type=SubAgentType(data.get("subagent_type", SubAgentType.TASK.value)),
            agent_key=str(data.get("agent_key", "")),
            custom_system_prompt=data.get("custom_system_prompt"),
            subagent_model=data.get("subagent_model"),
            model=data.get("model"),
            provider_key=data.get("provider_key"),
            user_invocable=data.get("user_invocable", True),
        )


@dataclass
class SubAgentResult:
    content: str = ""
    success: bool = True
    duration_ms: int = 0
    tool_calls: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    isolation_worktree_path: Path | None = None
    isolation_branch: str | None = None
    subagent_type: SubAgentType | None = None
    agent_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "tool_calls": self.tool_calls,
            "token_usage": self.token_usage,
            "error": self.error,
            "isolation_worktree_path": str(self.isolation_worktree_path) if self.isolation_worktree_path else None,
            "isolation_branch": self.isolation_branch,
            "subagent_type": self.subagent_type.value if self.subagent_type else None,
            "agent_key": self.agent_key,
        }

    def to_response_text(self) -> str:
        st = self.subagent_type.value if self.subagent_type else "unknown"
        key = self.agent_key or st
        lines = [
            f"Sub-agent ({key}) Result:",
            f"Content: {self.content}",
        ]
        if self.duration_ms > 0:
            lines.append(f"Duration: {self.duration_ms} ms")
        if self.tool_calls > 0:
            lines.append(f"Tool calls: {self.tool_calls}")
        if self.token_usage:
            total = self.token_usage.get("input", 0) + self.token_usage.get("output", 0)
            lines.append(f"Token usage: {total}")
        if not self.success:
            lines.append("Status: failed")
            if self.error:
                lines.append(f"Error: {self.error}")
        return "\n".join(lines)


class SubAgent:
    def __init__(
        self,
        context: SubAgentContext,
        hook_engine: HookEngine | None = None,
        provider: Any = None,
        available_tools: list[BaseTool] | None = None,
        permission_client: Any | None = None,
    ) -> None:
        self._context = context
        self._hook_engine = hook_engine
        self._provider = provider
        self._available_tools = filter_delegate_tools(available_tools or [])
        self._permission_client = permission_client
        self._start_time: float = 0.0
        self._tool_call_count: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._collected_content: list[str] = []
        self._result: SubAgentResult | None = None
        self._isolation_worktree_path: Path | None = None
        self._isolation_branch: str | None = None
        self._is_complete: bool = False

    @property
    def context(self) -> SubAgentContext:
        return self._context

    @property
    def result(self) -> SubAgentResult | None:
        return self._result

    @property
    def is_complete(self) -> bool:
        return self._is_complete

    def get_system_prompt(self) -> str:
        if self._context.custom_system_prompt:
            base = self._context.custom_system_prompt.strip() + "\n\n"
        else:
            base = (
                f"You are a specialized sub-agent (type '{self._context.subagent_type.value}').\n\n"
            )
        base += f"Your task is:\n{self._context.task}\n\n"
        base += "Complete the task and return a concise summary."
        return base

    def _get_tool_subset(self) -> list[str]:
        tool_subset: list[str] = []
        for tool_name in self._context.allowed_tools:
            for tool in self._available_tools:
                if tool and tool.info().name == tool_name:
                    tool_subset.append(tool_name)
                    break
        return tool_subset

    def _get_tools_for_subset(self, tool_names: list[str]) -> list[BaseTool]:
        tools: list[BaseTool] = []
        for tool_name in tool_names:
            for tool in self._available_tools:
                if tool and tool.info().name == tool_name:
                    tools.append(tool)
                    break
        return tools

    async def _setup_worktree(self, worktree_path: Path) -> None:
        import subprocess

        def _sync() -> None:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=self._context.working_directory,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    logger.error("Not a git repository: %s", result.stderr)
                    return
                repo_root = Path(result.stdout.strip())
                worktree_path.parent.mkdir(parents=True, exist_ok=True)
                branch_name = f"subagent-{self._context.session_id}"
                add = subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
                if add.returncode != 0:
                    logger.error("Failed to create worktree: %s", add.stderr)
                    return
                self._isolation_worktree_path = worktree_path
                self._isolation_branch = branch_name
                logger.debug("Created worktree at %s", worktree_path)
            except Exception as e:
                logger.error("Error creating worktree: %s", e)

        await asyncio.to_thread(_sync)

    async def _cleanup_worktree(self, force: bool = False) -> None:
        if not self._isolation_worktree_path:
            return
        import shutil
        import subprocess

        path = self._isolation_worktree_path
        branch = self._isolation_branch
        repo_cwd = self._context.working_directory

        def _sync() -> None:
            try:
                args = ["git", "worktree", "remove", str(path)]
                if force:
                    args.append("-f")
                result = subprocess.run(
                    args,
                    cwd=repo_cwd,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    rm = subprocess.run(
                        ["git", "worktree", "remove", "-f", str(path)],
                        cwd=repo_cwd,
                        capture_output=True,
                        text=True,
                    )
                    if rm.returncode != 0:
                        logger.error("Failed to remove worktree: %s", rm.stderr)
                        shutil.rmtree(path, ignore_errors=True)
                if branch:
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        cwd=repo_cwd,
                        capture_output=True,
                        text=True,
                    )
            except Exception as e:
                logger.warning("Error cleaning worktree: %s", e)
            finally:
                self._isolation_worktree_path = None
                self._isolation_branch = None

        await asyncio.to_thread(_sync)

    async def run(self) -> AsyncIterator[Any]:
        from ..agent import Agent, AgentEvent, AgentEventType

        self._start_time = time.time()
        self._is_complete = False
        self._tool_call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._collected_content = []
        collected_content: list[str] = []
        work_path: Path | None = None
        try:
            if self._hook_engine:
                hook_context = {
                    "subagent_id": self._context.session_id,
                    "subagent_type": self._context.subagent_type.value,
                    "agent_key": self._context.agent_key,
                    "task": self._context.task,
                    "session_id": self._context.session_id,
                    "working_directory": self._context.working_directory,
                    "timeout_ms": self._context.timeout_ms,
                    "max_iterations": self._context.max_iterations,
                    "isolation_mode": self._context.isolation_mode.value,
                    "allowed_tools": self._context.allowed_tools,
                }
                try:
                    await asyncio.wait_for(
                        self._hook_engine.fire(
                            HookEvent.SubagentStart,
                            context=hook_context,
                            provider=self._provider,
                            working_directory=self._context.working_directory,
                            suppress_agent_hooks=False,
                        ),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("SubagentStart hook timed out (10s)")
                except Exception as e:
                    logger.warning("SubagentStart hook failed: %s", e)

            if self._context.isolation_mode == IsolationMode.WORKTREE:
                base = Path(self._context.working_directory) / ".clawcode-subagent-worktrees"
                base.mkdir(parents=True, exist_ok=True)
                work_path = Path(
                    tempfile.mkdtemp(
                        prefix=f"w-{self._context.session_id}-",
                        dir=str(base),
                    )
                )
                await self._setup_worktree(work_path)

            effective_cwd = str(self._isolation_worktree_path or self._context.working_directory)

            provider = self._provider
            if not provider:
                provider = await self._create_provider()
                if not provider:
                    logger.error("Failed to create provider for subagent")
                    collected_content.append("\n[Error] Failed to create provider for subagent\n")
                    self._is_complete = False
                    return

            tools = self._get_tools_for_subset(self._get_tool_subset())
            # Pass the hook engine so subagents inherit PreToolUse / PostToolUse
            # policies from the parent. Session-level hooks are suppressed inside
            # Agent.run via suppress_agent_hooks, so only tool-level hooks fire.
            _settings_obj = None
            try:
                from ...config import get_settings

                _settings_obj = get_settings()
            except Exception:
                _settings_obj = None
            agent = Agent(
                provider=provider,
                tools=tools,
                message_service=_SubAgentMemoryMessageService(),
                session_service=_SubAgentMemorySessionService(),
                system_prompt=self.get_system_prompt(),
                max_iterations=self._context.max_iterations,
                working_directory=effective_cwd,
                hook_engine=self._hook_engine,
                settings=_settings_obj,
                permission_client=self._permission_client,
            )
            loop_error: str | None = None
            hud_id_prefix = f"sub:{self._context.session_id}:"
            run_session_id = (self._context.parent_session_id or "").strip() or self._context.session_id

            def _prefixed_tool_call_id(raw: str | None) -> str:
                rid = (raw or "").strip() or str(uuid.uuid4())
                if rid.startswith("sub:"):
                    return rid
                return f"{hud_id_prefix}{rid}"

            try:
                async for event in agent.run(
                    session_id=run_session_id,
                    content=self._build_user_message(),
                    iteration_budget=self._context.iteration_budget,
                ):
                    if event.type == AgentEventType.CONTENT_DELTA and event.content:
                        collected_content.append(event.content)
                        self._collected_content.append(event.content)
                        yield event
                    elif event.type == AgentEventType.USAGE and event.usage:
                        self._total_input_tokens += event.usage.input_tokens
                        self._total_output_tokens += event.usage.output_tokens
                    elif event.type == AgentEventType.TOOL_USE and event.tool_name:
                        self._tool_call_count += 1
                        pid = _prefixed_tool_call_id(event.tool_call_id)
                        yield replace(
                            event,
                            tool_call_id=pid,
                            hud_only=True,
                        )
                    elif event.type == AgentEventType.TOOL_RESULT:
                        if event.tool_call_id:
                            pid = _prefixed_tool_call_id(event.tool_call_id)
                            yield replace(
                                event,
                                tool_call_id=pid,
                                hud_only=True,
                            )
                    elif event.type == AgentEventType.THINKING:
                        # Do not leak chain-of-thought deltas into user-visible tool
                        # output. Subagent thinking can be highly fragmented and causes
                        # noisy "[Thinking]" floods in the parent TUI stream.
                        pass
                    elif event.type == AgentEventType.RESPONSE and event.message:
                        if event.message and event.message.content:
                            collected_content.append(event.message.content)
                    elif event.type == AgentEventType.ERROR and event.error:
                        collected_content.append(f"\n[Error] {event.error}")
                        loop_error = str(event.error)
                        self._is_complete = False
                        break
                else:
                    self._is_complete = loop_error is None
            except asyncio.TimeoutError:
                collected_content.append(
                    f"\n[Timed out after {self._context.timeout_ms / 1000}s]"
                )
                self._is_complete = False
            except Exception as e:
                logger.error("Error in subagent execution: %s", e)
                collected_content.append(f"\n[Error] {e}")
                loop_error = str(e)
                self._is_complete = False
        finally:
            duration_ms = int((time.time() - self._start_time) * 1000)
            content_text = sanitize_text("".join(collected_content))
            err_msg: str | None = None
            if not self._is_complete:
                err_msg = next(
                    (ln for ln in content_text.splitlines() if ln.startswith("[Error]")),
                    None,
                ) or "Subagent did not complete successfully"
            self._result = SubAgentResult(
                content=content_text,
                success=self._is_complete,
                duration_ms=duration_ms,
                tool_calls=self._tool_call_count,
                token_usage={
                    "input": self._total_input_tokens,
                    "output": self._total_output_tokens,
                },
                error=err_msg,
                isolation_worktree_path=self._isolation_worktree_path,
                isolation_branch=self._isolation_branch,
                subagent_type=self._context.subagent_type,
                agent_key=self._context.agent_key,
            )

            if self._hook_engine:
                try:
                    await asyncio.wait_for(
                        self._hook_engine.fire(
                            HookEvent.SubagentStop,
                            context={
                                "subagent_id": self._context.session_id,
                                "subagent_type": self._context.subagent_type.value,
                                "agent_key": self._context.agent_key,
                                "task": self._context.task,
                                "session_id": self._context.session_id,
                                "result": self._result.to_dict() if self._result else None,
                                "success": self._is_complete,
                                "duration_ms": duration_ms,
                                "tool_calls": self._tool_call_count,
                                "token_usage": self._result.token_usage if self._result else {},
                                "isolation_mode": self._context.isolation_mode.value,
                                "isolation_worktree_path": str(self._isolation_worktree_path)
                                if self._isolation_worktree_path
                                else None,
                                "isolation_branch": self._isolation_branch,
                            },
                            provider=self._provider,
                            working_directory=self._context.working_directory,
                            suppress_agent_hooks=False,
                        ),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("SubagentStop hook timed out (10s)")
                except Exception as e:
                    logger.warning("SubagentStop hook failed: %s", e)

            if self._isolation_worktree_path:
                await self._cleanup_worktree(force=True)

            yield AgentEvent(
                type=AgentEventType.CONTENT_DELTA,
                content=f"\n[Sub-agent] completed in {duration_ms}ms\n",
            )

    def _build_user_message(self) -> str:
        return f"Please complete this task:\n{self._context.task}"

    def _resolve_model_id(self, settings: Any) -> str:
        hint = (
            self._context.subagent_model
            or self._context.model
            or ""
        ).strip().lower()
        base_cfg = settings.get_agent_config(self._get_agent_type_config())
        base_model = base_cfg.model
        if not hint or hint in ("inherit", "inherited", "default"):
            return base_model
        if hint in ("sonnet", "opus", "haiku"):
            for agent_name in ("coder", "task"):
                cfg = settings.get_agent_config(agent_name)
                m = (cfg.model or "").lower()
                if hint == "sonnet" and "sonnet" in m:
                    return cfg.model
                if hint == "haiku" and "haiku" in m:
                    return cfg.model
                if hint == "opus" and "opus" in m:
                    return cfg.model
            return base_model
        return self._context.subagent_model or self._context.model or base_model

    async def _create_provider(self) -> Any:
        if self._provider:
            return self._provider
        try:
            from ...config import get_settings
            from ..providers import create_provider, resolve_provider_from_model

            settings = get_settings()
            agent_type_config = self._get_agent_type_config()
            agent_config = settings.get_agent_config(agent_type_config)
            model_id = self._resolve_model_id(settings)
            provider_name, provider_key = resolve_provider_from_model(
                model_id, settings, agent_config,
            )
            provider_cfg = settings.providers.get(provider_key)
            api_key = getattr(provider_cfg, "api_key", None) if provider_cfg else None
            base_url = getattr(provider_cfg, "base_url", None) if provider_cfg else None
            return create_provider(
                provider_name=provider_name,
                model_id=model_id,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as e:
            logger.error("Failed to create provider for subagent: %s", e)
            return None

    def _get_agent_type_config(self) -> str:
        type_to_config = {
            SubAgentType.EXPLORE: "coder",
            SubAgentType.CODER: "coder",
            SubAgentType.PLAN: "task",
            SubAgentType.TEST: "coder",
            SubAgentType.REVIEW: "coder",
            SubAgentType.CUSTOM: "coder",
            SubAgentType.GENERAL_PURPOSE: "coder",
            SubAgentType.CLAUDE_CODE_GUIDE: "task",
        }
        return type_to_config.get(self._context.subagent_type, "coder")


_AGENT_KEY_ALIASES: dict[str, str] = {
    "review": "code-review",
    "coder": "general-purpose",
    "custom": "general-purpose",
    "test": "general-purpose",
    "planner": "plan",
    "agent-plan": "plan",
    "agent-planner": "plan",
    "agent-explore": "explore",
    "agent-review": "code-review",
    "agent-code-review": "code-review",
    "agent-general-purpose": "general-purpose",
}


def _normalize_agent_key(raw_key: str) -> str:
    key = (raw_key or "").strip().lower()
    if key.startswith("agent-"):
        key = key[len("agent-"):].strip()
    return _AGENT_KEY_ALIASES.get(key, key)


def _enum_for_agent_key(key: str) -> SubAgentType:
    return SUBAGENT_BUILTIN_TYPES.get(key, SubAgentType.CUSTOM)


async def _drain_subagent(subagent: SubAgent) -> None:
    gen = subagent.run()
    try:
        async for _ in gen:
            pass
    finally:
        await gen.aclose()


@dataclass
class SubagentRunFinal:
    """Terminal value from `AgentTool.forward_subagent_events` (not streamed as AgentEvent)."""

    response: ToolResponse


@dataclass
class _PreparedSubagent:
    subagent: SubAgent
    timeout_s: float
    agent_key: str
    sub_ty: SubAgentType
    isolation_mode: IsolationMode
    internal_allowed: list[str]


class AgentTool(BaseTool):
    """Claude Code `Agent` tool (alias `Task`)."""

    def __init__(
        self,
        permissions: Any = None,
        session_service: Any = None,
        message_service: Any = None,
        hook_engine: HookEngine | None = None,
        provider: Any = None,
        available_tools: list[BaseTool] | None = None,
    ) -> None:
        self._permissions = permissions
        self._session_service = session_service
        self._message_service = message_service
        self._hook_engine = hook_engine
        self._provider = provider
        self._available_tools = filter_delegate_tools(available_tools or [])
        self._active_subagents: dict[str, SubAgent] = {}

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="Agent",
            description=(
                "Spawn a subagent with an isolated context (Claude Code Agent tool). "
                "Use built-in agents: explore, plan, general-purpose, code-review; "
                "or custom agents from .claude/agents/. "
                "Pass the task in `prompt` or `task`. Set `agent` or `subagent_type` to the agent name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "Agent name (e.g. explore, plan, general-purpose, code-review, or a custom agent id).",
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "Alias of `agent` for compatibility with older Task tool calls.",
                    },
                    "task": {
                        "type": "string",
                        "description": "Instructions for the subagent (alias: prompt).",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Alias of `task` (Claude Code convention).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional short description (may be used like task if task empty).",
                    },
                    "context": {
                        "type": "string",
                        "description": "Extra context appended to the user message.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 300, max: 600).",
                        "default": 300,
                        "minimum": 10,
                        "maximum": 600,
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum ReAct iterations (default: from agent definition or 20).",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "isolation": {
                        "type": "string",
                        "description": "Isolation mode: none, worktree, fork.",
                        "enum": ["none", "worktree", "sandbox", "container", "fork"],
                        "default": "none",
                    },
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Override allowed tools (ClawCode internal or Claude names).",
                    },
                },
                "required": [],
            },
            required=[],
        )

    def _prepare_subagent_run(
        self, call: ToolCall, context: ToolContext
    ) -> _PreparedSubagent | ToolResponse:
        params = call.input if isinstance(call.input, dict) else {}
        raw_key = (
            params.get("agent")
            or params.get("subagent_type")
            or "general-purpose"
        )
        key = _normalize_agent_key(str(raw_key))

        task = (
            (params.get("task") or params.get("prompt") or params.get("description") or "")
        )
        task = str(task).strip()
        extra = str(params.get("context") or "").strip()
        if extra:
            task = f"{task}\n\nAdditional context:\n{extra}" if task else extra
        if not task:
            return ToolResponse(
                content="Error: provide `task` or `prompt` (instructions for the subagent).",
                is_error=True,
            )

        timeout = float(min(int(params.get("timeout", 300)), 600))
        max_iterations = int(params.get("max_iterations", DEFAULT_MAX_ITERATIONS))
        isolation_raw = params.get("isolation")
        allowed_override = params.get("allowed_tools")

        registry = load_merged_agent_definitions(context.working_directory or ".")
        original_key = key
        dfn = registry.get(key)
        if not dfn:
            candidates = sorted(registry.keys())
            if candidates:
                # Prefer same family (e.g. clawteam-*) when available.
                prefix = key.split("-", 1)[0]
                scoped = [c for c in candidates if c.startswith(prefix + "-")]
                pool = scoped or candidates
                best = difflib.get_close_matches(key, pool, n=1, cutoff=0.45)
                if best:
                    key = best[0]
                    dfn = registry.get(key)
        if not dfn:
            known = ", ".join(sorted(registry.keys()))
            return ToolResponse(
                content=f"Error: unknown agent '{key}'. Known agents: {known}",
                is_error=True,
            )

        iso = str(isolation_raw or dfn.isolation or "none").strip().lower()
        try:
            isolation_mode = IsolationMode(iso)
        except ValueError:
            isolation_mode = IsolationMode.NONE

        if allowed_override is not None and isinstance(allowed_override, list):
            internal_allowed = normalize_claude_tool_list([str(x) for x in allowed_override])
            internal_allowed = [n for n in internal_allowed if n not in DELEGATE_TOOL_NAMES]
        else:
            internal_allowed = compute_allowed_internal_tools(
                self._available_tools,
                dfn.tools,
                dfn.disallowed_tools,
            )

        if bool(getattr(context, "plan_mode", False)):
            if key not in PLAN_ALLOWED_SUBAGENTS:
                return ToolResponse(
                    content=(
                        f"Error: subagent '{key}' is not allowed in /plan mode. "
                        f"Use one of: {', '.join(sorted(PLAN_ALLOWED_SUBAGENTS))}."
                    ),
                    is_error=True,
                )
            internal_allowed = filter_read_only_tools(internal_allowed)

        max_iter = dfn.max_turns if dfn.max_turns is not None else max_iterations

        sub_ty = _enum_for_agent_key(key)
        sub_ctx = SubAgentContext(
            task=task,
            session_id=str(uuid.uuid4().hex[:8]),
            parent_session_id=context.session_id,
            working_directory=context.working_directory or "",
            allowed_tools=internal_allowed,
            max_iterations=max_iter,
            timeout_ms=int(timeout * 1000),
            isolation_mode=isolation_mode,
            subagent_type=sub_ty,
            agent_key=key,
            custom_system_prompt=dfn.prompt or None,
            subagent_model=dfn.model,
            iteration_budget=None,
        )

        subagent = SubAgent(
            context=sub_ctx,
            hook_engine=self._hook_engine,
            provider=self._provider,
            available_tools=self._available_tools,
            permission_client=context.permission_service,
        )
        return _PreparedSubagent(
            subagent=subagent,
            timeout_s=timeout,
            agent_key=key,
            sub_ty=sub_ty,
            isolation_mode=isolation_mode,
            internal_allowed=internal_allowed,
        )

    async def forward_subagent_events(
        self, call: ToolCall, context: ToolContext
    ) -> AsyncIterator[Any]:
        """Run nested agent and yield HUD tool events (TOOL_USE / TOOL_RESULT with hud_only).

        Ends with a single `SubagentRunFinal` carrying the same `ToolResponse` as `run()`.
        """
        from ..agent import AgentEventType

        prepared = self._prepare_subagent_run(call, context)
        if isinstance(prepared, ToolResponse):
            yield SubagentRunFinal(prepared)
            return

        p = prepared
        sid = p.subagent.context.session_id
        self._active_subagents[sid] = p.subagent
        try:
            try:
                async with asyncio.timeout(p.timeout_s):
                    async for ev in p.subagent.run():
                        if ev.type in (
                            AgentEventType.TOOL_USE,
                            AgentEventType.TOOL_RESULT,
                        ):
                            yield ev
            except TimeoutError:
                yield SubagentRunFinal(
                    ToolResponse(
                        content=f"Sub-agent timed out after {int(p.timeout_s)} seconds.",
                        is_error=True,
                    )
                )
                return
            except Exception as e:
                logger.error("Error running sub-agent: %s", e)
                yield SubagentRunFinal(
                    ToolResponse(
                        content=f"Error running sub-agent: {e}",
                        is_error=True,
                    )
                )
                return
        finally:
            self._active_subagents.pop(sid, None)

        result = p.subagent.result
        if not result:
            yield SubagentRunFinal(
                ToolResponse(
                    content="Error: subagent produced no result",
                    is_error=True,
                )
            )
            return

        meta = {
            "agent": p.agent_key,
            "subagent_type": p.sub_ty.value,
            "isolation_mode": p.isolation_mode.value,
            "allowed_tools": p.internal_allowed,
        }
        yield SubagentRunFinal(
            ToolResponse(
                content=result.to_response_text(),
                metadata=json.dumps(meta),
            )
        )

    async def run(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        prepared = self._prepare_subagent_run(call, context)
        if isinstance(prepared, ToolResponse):
            return prepared

        p = prepared
        sid = p.subagent.context.session_id
        self._active_subagents[sid] = p.subagent
        try:
            await asyncio.wait_for(_drain_subagent(p.subagent), timeout=p.timeout_s)
        except asyncio.TimeoutError:
            return ToolResponse(
                content=f"Sub-agent timed out after {int(p.timeout_s)} seconds.",
                is_error=True,
            )
        except Exception as e:
            logger.error("Error running sub-agent: %s", e)
            return ToolResponse(
                content=f"Error running sub-agent: {e}",
                is_error=True,
            )
        finally:
            self._active_subagents.pop(sid, None)

        result = p.subagent.result
        if not result:
            return ToolResponse(content="Error: subagent produced no result", is_error=True)

        meta = {
            "agent": p.agent_key,
            "subagent_type": p.sub_ty.value,
            "isolation_mode": p.isolation_mode.value,
            "allowed_tools": p.internal_allowed,
        }
        return ToolResponse(
            content=result.to_response_text(),
            metadata=json.dumps(meta),
        )

    @property
    def requires_permission(self) -> bool:
        return True

    @property
    def is_dangerous(self) -> bool:
        return True


def create_agent_tool(
    permissions: Any = None,
    session_service: Any = None,
    message_service: Any = None,
    hook_engine: HookEngine | None = None,
    provider: Any = None,
    available_tools: list[BaseTool] | None = None,
) -> AgentTool:
    return AgentTool(
        permissions=permissions,
        session_service=session_service,
        message_service=message_service,
        hook_engine=hook_engine,
        provider=provider,
        available_tools=available_tools,
    )


def create_subagent_tool(
    permissions: Any = None,
    session_service: Any = None,
    message_service: Any = None,
    hook_engine: HookEngine | None = None,
    provider: Any = None,
    available_tools: list[BaseTool] | None = None,
) -> AgentTool:
    """Backward-compatible alias; returns the same Agent tool."""
    return create_agent_tool(
        permissions=permissions,
        session_service=session_service,
        message_service=message_service,
        hook_engine=hook_engine,
        provider=provider,
        available_tools=available_tools,
    )


__all__ = [
    "SubAgent",
    "SubAgentContext",
    "SubAgentResult",
    "SubAgentType",
    "SubAgentEventType",
    "IsolationMode",
    "AgentTool",
    "SubagentRunFinal",
    "create_agent_tool",
    "create_subagent_tool",
    "READ_ONLY_TOOLS",
    "CODER_TOOLS",
    "PLAN_TOOLS",
    "TEST_TOOLS",
    "REVIEW_TOOLS",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_ISOLATION_MODE",
    "CLAUDE_TO_CLAW_TOOL",
    "filter_delegate_tools",
    "compute_allowed_internal_tools",
    "normalize_claude_tool_list",
]
