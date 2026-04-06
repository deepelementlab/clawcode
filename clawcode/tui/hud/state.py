from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal


HudAgentStatus = Literal["running", "completed"]


@dataclass
class HudAgentEntry:
    """Track sub-agent status derived from the `agent` tool calls."""

    id: str
    subagent_type: str
    description: str
    model: Optional[str] = None
    status: HudAgentStatus = "running"
    start_time: float = 0.0  # time.monotonic()
    end_time: Optional[float] = None  # time.monotonic()


@dataclass
class HudRunningTool:
    """Tool currently executing (shown as ◐ on HUD tools line, claude-hud style)."""

    name: str
    target: str = ""


HudTodoStatus = Literal["pending", "in_progress", "completed"]


@dataclass
class HudTodoItem:
    """Todo item shown in the HUD, aggregated from runtime tool events."""

    content: str
    status: HudTodoStatus = "pending"


@dataclass
class HudConfigCounts:
    """Static config statistics shown in the HUD."""

    claude_md_count: int = 0
    rules_count: int = 0
    mcp_count: int = 0
    hooks_count: int = 0


@dataclass
class HudState:
    """Aggregate HUD state that can be rendered to a multi-line string."""

    model: str = ""
    context_percent: int = 0
    context_window_size: int = 0

    config_counts: HudConfigCounts = field(default_factory=HudConfigCounts)
    session_duration: str = ""
    # Last 1–2 path segments of working dir (claude-hud session-line project hint).
    project_hint: str = ""

    tool_counts: Dict[str, int] = field(default_factory=dict)
    running_tools: List[HudRunningTool] = field(default_factory=list)
    agent_entries: List[HudAgentEntry] = field(default_factory=list)
    todos: List[HudTodoItem] = field(default_factory=list)

    # Non-empty when a clawteam deep_loop is active; rendered on row 5 (overrides todos row).
    deep_loop_status: str = ""

