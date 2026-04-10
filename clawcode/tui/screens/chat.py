"""Chat screen for ClawCode TUI.

This module provides the main chat interface screen where users interact
with the AI agent.
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from ...app import AppContext
    from ...config import Settings
    from ...llm.agent import AgentEvent
    from ...llm.claw import ClawAgent

from ...integrations.git_workspace import git_restore_tracked_paths_to_head
from ...llm.plan_store import PlanBundle, PlanTaskItem
from ...llm.plan_tasks import compose_task_execution_prompt, split_plan_to_tasks
from ...llm.ecc_planner_prompt import ECC_PLANNER_MD
from ..builtin_slash import BUILTIN_SLASH_NAMES, BuiltinSlashContext, parse_slash_line
from ..builtin_slash_handlers import handle_builtin_slash
from ..clawteam_deeploop_pending import (
    clawteam_deeploop_clear_pending,
    clawteam_deeploop_get_pending,
    clawteam_deeploop_set_pending,
)
from ..code_awareness.monitor import ArchitectureAwarenessMonitor
from ..code_awareness.widget import CodeAwarenessPanel
from ..components.chat.claude_input import ClaudeCodeInput
from ..components.chat.input_history_store import InputHistoryStore
from ..components.chat.hud_bar import HudBar
from ..components.chat.info_panel import InfoPanel, InfoPanelModel, format_lsp_lines
from ..components.chat.input_area import MessageInput
from ..components.chat.message_list import (
    MessageList,
    refresh_message_lists_on_screen,
    set_conversation_style_for_mode,
)
from ..components.chat.opencode_input import OpenCodeInput
from ..components.chat.plan_panel import PlanPanel
from ..components.chat.right_panel_grip import (
    RightPanelGrip,
    RightPanelWidthCommit,
    RightPanelWidthDrag,
)
from ..ui_style import (
    derive_scene_tags,
    load_ui_anti_patterns,
    load_ui_anti_pattern_rules,
    is_ui_intent,
    ui_critic_checklist,
    ui_style_auto_pick_top_n,
    load_agent_scene_tags,
    load_ui_catalog,
    select_ui_style_auto,
    style_prompt_prefix,
    ui_catalog_candidate_hints,
)
from ..components.chat.sidebar import Sidebar
from ..components.dialogs.display_mode import DisplayModeDialog
from ..components.dialogs.file_picker import FileAttachment, FilePickerDialog
from ..components.dialogs.git_restore import GitRestoreDialog
from ..hud import (
    HudAgentEntry,
    HudConfigCounts,
    HudRunningTool,
    HudState,
    HudTodoItem,
    count_configs,
    get_context_window_size,
)
from ..hud.render import format_hud_session_duration
from ..hud.tool_target import extract_tool_target_for_hud

# Built-in slash commands that may take noticeable time (DB/network/git/LLM).
# Keep this list centralized so newly added long-running slash handlers
# are less likely to miss immediate UI acknowledgement.
_SLOW_BUILTIN_SLASH_PRE_ECHO = frozenset(
    {
        "compact",
        "review",
        "code-review",
        "security-review",
        "architect",
        "multi-plan",
        "multi-execute",
        "multi-backend",
        "multi-frontend",
        "multi-workflow",
        "orchestrate",
        "pr-comments",
        "rewind",
        "export",
        "fork",
        "copy",
        "diff",
        "status",
        "release-notes",
        "insights",
        "learn",
        "learn-orchestrate",
        "experience-dashboard",
        "instinct-status",
        "instinct-import",
        "instinct-export",
        "evolve",
        "experience-create",
        "experience-status",
        "experience-export",
        "experience-import",
        "experience-apply",
        "experience-feedback",
        "team-experience-create",
        "team-experience-status",
        "team-experience-export",
        "team-experience-import",
        "team-experience-apply",
        "team-experience-feedback",
        "tecap-create",
        "tecap-status",
        "tecap-export",
        "tecap-import",
        "tecap-apply",
        "tecap-feedback",
    }
)


_PLUGIN_NAMESPACE_CMD = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")

_logger = logging.getLogger(__name__)


def _parse_plugin_namespace_slash(raw_text: str) -> tuple[str, str] | None:
    """Parse `/plugin:<command> [tail]` and return (command, tail)."""
    raw = (raw_text or "").strip()
    if not raw.startswith("/plugin:"):
        return None
    rest = raw[len("/plugin:") :].strip()
    if not rest:
        return None
    head, sep, tail = rest.partition(" ")
    if not _PLUGIN_NAMESPACE_CMD.match(head):
        return None
    return head, tail.strip() if sep else ""


def _plugin_slash_reply_ok_for_skill_refresh(reply: str | None) -> bool:
    """True when /plugin handling did not end in a parse or fetch error (safe to rescan skills for `/`)."""
    r = (reply or "").lstrip()
    if r.startswith("Error:"):
        return False
    if r.startswith("Invalid /plugin"):
        return False
    return True


def _parse_clawteam_namespace_slash(raw_text: str) -> tuple[str, str] | None:
    """Parse `/clawteam:<agent> [tail]` and return (agent, tail)."""
    raw = (raw_text or "").strip()
    if not raw.startswith("/clawteam:"):
        return None
    rest = raw[len("/clawteam:") :].strip()
    if not rest:
        return None
    head, sep, tail = rest.partition(" ")
    if not _PLUGIN_NAMESPACE_CMD.match(head):
        return None
    return head, tail.strip() if sep else ""


def _extract_deep_loop_eval(text: str) -> tuple[bool, float | None, bool]:
    """Parse deep loop convergence signal from assistant text.

    Returns:
        (converged, delta_score, has_eval_marker) where *has_eval_marker* is True
        when the assistant actually produced a ``DEEP_LOOP_EVAL_JSON:`` line (even if
        the payload was malformed).  Callers use this flag to detect when the model
        silently dropped the eval contract.
    """
    raw = str(text or "")
    marker = "DEEP_LOOP_EVAL_JSON:"
    converged: bool | None = None
    delta_score: float | None = None

    pos = raw.rfind(marker)
    has_eval_marker = pos >= 0
    if has_eval_marker:
        payload = raw[pos + len(marker) :].strip()
        line = payload.splitlines()[0].strip() if payload else ""
        if line:
            # Strict JSON first.
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    c = obj.get("converged")
                    if isinstance(c, bool):
                        converged = c
                    ds = obj.get("delta_score")
                    if isinstance(ds, (int, float)):
                        delta_score = float(ds)
            except Exception:
                # Fallback: Python-literal dict style with single quotes.
                normalized = re.sub(r"\btrue\b", "True", line, flags=re.IGNORECASE)
                normalized = re.sub(r"\bfalse\b", "False", normalized, flags=re.IGNORECASE)
                normalized = re.sub(r"\bnull\b", "None", normalized, flags=re.IGNORECASE)
                try:
                    obj2 = ast.literal_eval(normalized)
                    if isinstance(obj2, dict):
                        c2 = obj2.get("converged")
                        if isinstance(c2, bool):
                            converged = c2
                        ds2 = obj2.get("delta_score")
                        if isinstance(ds2, (int, float)):
                            delta_score = float(ds2)
                except Exception:
                    pass

    # Text fallback for both fields.
    if converged is None:
        m_c = re.search(r"\bconverged\s*[:=]\s*(true|false)\b", raw, flags=re.IGNORECASE)
        if m_c:
            converged = m_c.group(1).lower() == "true"
    if delta_score is None:
        m_d = re.search(r"\bdelta_score\s*[:=]\s*(-?\d+(?:\.\d+)?)\b", raw, flags=re.IGNORECASE)
        if m_d:
            try:
                delta_score = float(m_d.group(1))
            except Exception:
                delta_score = None
    return bool(converged), delta_score, has_eval_marker


def _hud_project_hint(hud_dir: str) -> str:
    """Last path segments for HUD; avoid useless Windows-only hints like `D:`."""
    try:
        from pathlib import Path

        p = Path(hud_dir).expanduser().resolve()
        uni = str(p).replace("\\", "/")
        segs = [x for x in uni.split("/") if x]
        if len(segs) >= 2:
            return f"{segs[-2]}/{segs[-1]}"
        if len(segs) == 1:
            one = segs[0]
            if len(one) <= 3 and ":" in one:
                tail = uni.replace("\\", "/").lstrip("/")
                if len(tail) > 44:
                    return "..." + tail[-41:]
                return tail
            return one
    except Exception:
        return ""
    return ""


def _has_hud_rule_signals(dir_path: Path) -> bool:
    """Best-effort project root detection for claude-hud-like config counts.

    We intentionally look for directories/markers (fast) rather than scanning all md files (slow).
    """
    # Claude Code counts (mirrors clawcode/tui/hud/config_reader.py intent).
    return any(
        [
            (dir_path / ".cursor" / "rules").is_dir(),
            (dir_path / ".claude" / "rules").is_dir(),
            (dir_path / ".cursorrules").is_dir(),
            (dir_path / ".cursorrules").is_file(),
            (dir_path / "CLAUDE.md").is_file(),
            (dir_path / "CLAUDE.local.md").is_file(),
        ]
    )


@dataclass
class SessionRunState:
    session_id: str
    run_id: str = ""
    task: asyncio.Task[None] | None = None
    is_processing: bool = False
    spinner_frame: int = 0
    has_unread_output: bool = False
    waiting_permission: bool = False
    last_error: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    # HUD ???????: last completed user-message turn (shown while idle; overwritten each run).
    last_turn_duration_str: str | None = None
    is_plan_run: bool = False
    is_claw_run: bool = False
    plan_user_request: str = ""
    plan_artifact_scope: str = ""
    plan_routing_meta: dict[str, Any] = field(default_factory=dict)
    # When set, persist final assistant markdown to PlanStore under this subdir without plan_mode.
    response_artifact_subdir: str = ""
    build_task_index: int = -1


@dataclass
class PlanSessionState:
    session_id: str
    mode: str = "normal"  # normal | plan_pending | arc_plan_pending | plan_ready | executing_from_plan
    last_plan_path: str | None = None
    last_plan_text: str = ""
    last_user_request: str = ""
    bundle: PlanBundle | None = None


@dataclass
class SessionUiState:
    session_id: str
    message_list: MessageList | None = None
    history_loaded: bool = False


# HUD: sub-agents / todo tools don't appear on the tools summary line (claude-hud semantics).
_HUD_SKIP_RUNNING_LINE_TOOLS = frozenset(
    {"TodoWrite", "TaskCreate", "TaskUpdate", "agent", "Agent", "Task"}
)
_HUD_AGENT_TOOLS = frozenset({"agent", "Agent", "Task"})


class ChatScreen(Screen):
    """Main chat interface screen.

    This screen displays the conversation with the AI agent,
    handles user input, and manages the ReAct loop integration.
    """

    # App already loads the main stylesheet; avoid duplicate relative CSS loading.
    CSS_PATH = None
    _BUILD_WATCHDOG_INTERVAL_S = 2.0
    _BUILD_STALL_TIMEOUT_S = 90
    _BUILD_STALL_TIMEOUT_REASONER_S = 210
    _BUILD_STALL_GRACE_COUNT = 1
    _BUILD_MAX_RETRIES_PER_TASK = 2
    _PLAN_PANEL_REFRESH_MIN_INTERVAL_S = 0.6
    _RIGHT_PANEL_MIN_W = 24
    _RIGHT_PANEL_MAX_W = 90

    # Deep-loop background monitor
    _DEEP_LOOP_MONITOR_INTERVAL_S = 30.0   # watchdog check frequency
    _DEEP_LOOP_STALL_TIMEOUT_S    = 180.0  # idle seconds before treating loop as stalled
    _DEEP_LOOP_MAX_STALLS         = 5      # max auto-restart attempts before giving up

    BINDINGS = [
        ("f1", "show_help", "Help"),
        ("question_mark", "show_help", "Help"),
        ("ctrl+slash", "show_help", "Help"),
        ("ctrl+question", "show_help", "Help"),
        ("ctrl+shift+slash", "show_help", "Help"),
        ("alt+h", "show_help", "Help"),
        ("ctrl+h", "show_help", "Help"),
        ("ctrl+s", "send_message", "Send"),
        ("ctrl+e", "open_external_editor", "Editor"),
        ("ctrl+f", "open_file_picker", "Attach"),
        ("ctrl+u", "cancel_input", "Clear"),
        ("ctrl+y", "toggle_code_awareness_history", "History"),
        ("i", "enter_insert_mode", "Insert"),
        ("escape", "exit_insert_mode", "Normal"),
    ]

    def __init__(self, settings_or_context: Settings | AppContext) -> None:
        """Initialize the chat screen.

        Args:
            settings_or_context: Application settings or AppContext from create_app()
        """
        super().__init__()
        if hasattr(settings_or_context, "session_service"):
            self._app_context: AppContext | None = settings_or_context
            self.settings = settings_or_context.settings
        else:
            self._app_context = None
            self.settings = settings_or_context
        self.current_session_id: str | None = None
        self._current_session_title: str | None = None
        self._agent: Any = None  # ClawAgent at runtime (extends Agent)
        self._claw_mode_enabled: bool = False
        self._session_runs: dict[str, SessionRunState] = {}
        self._session_ui: dict[str, SessionUiState] = {}
        self._plan_state: dict[str, PlanSessionState] = {}
        self._plan_store: Any = None
        self._processing_timer = None
        self._deep_loop_monitor_timer = None  # dedicated monitor; runs between iterations
        self._last_build_watchdog_check: float = 0.0
        self._last_plan_panel_refresh_at: float = 0.0
        self._switch_generation = 0
        self._builtin_slash_inflight: bool = False
        self._sidebar_refresh_task: asyncio.Task[None] | None = None
        self._sidebar_refresh_pending = False
        self._display_mode: str = "opencode"
        self._session_prompt_tokens: int = 0
        self._session_completion_tokens: int = 0
        self._session_cost: float = 0.0
        self._code_awareness_monitor: ArchitectureAwarenessMonitor | None = None
        self._input_history_store: InputHistoryStore | None = None

        # HUD (Claude-HUD-like bottom monitor)
        self._hud_counts: HudConfigCounts = HudConfigCounts()
        self._hud_tool_counts: dict[str, int] = {}
        self._hud_agent_entries: dict[str, HudAgentEntry] = {}
        self._hud_max_agent_entries: int = 8
        self._hud_todos: list[HudTodoItem] = []
        # Map TaskCreate taskId -> index in _hud_todos (best-effort, mirrors claude-hud resolveTaskIndex behavior)
        self._hud_task_id_to_index: dict[str, int] = {}
        self._hud_running_tools: dict[str, HudRunningTool] = {}
        self._clawteam_deep_loop_state: dict[str, dict[str, Any]] = {}
        self._clawteam_deep_loop_last_response: dict[str, str] = {}
        self._hud_plugin_manager: Any = None
        self._hud_project_dir: str = ""
        self._hud_counts_last_refresh: float = 0.0
        self._hud_counts_refresh_interval_s: float = 3.0
        # Cumulative tokens seen from USAGE events during the current turn.
        self._hud_turn_input_tokens: int = 0
        self._hud_turn_output_tokens: int = 0
        # Approximate output chars (fallback when provider gives no streaming usage).
        self._hud_turn_output_chars: int = 0
        self._ui_style_mode: str = str(getattr(self.settings, "ui_style_mode", "off") or "off")
        self._ui_style_selected: str = str(getattr(self.settings, "ui_style_default_slug", "") or "")
        self._ui_style_source: str = "default" if self._ui_style_selected else ""
        self._ui_style_reason: str = ""
        self._ui_style_top_candidates: list[str] = []

        # Dirty-flag for batched HUD status bar refresh (avoids per-event full redraws).
        self._hud_dirty: bool = False
        # Track which chrome mode was last fully applied to avoid redundant re-paints.
        self._last_chrome_mode: str = ""

    def _clamp_right_panel_width(self, w: int) -> int:
        w = int(w)
        try:
            app = getattr(self, "app", None)
            sz = getattr(app, "size", None) if app is not None else None
            outer = int(getattr(sz, "width", 0) or 0)
            if outer > 16:
                max_by_app = max(self._RIGHT_PANEL_MIN_W, outer - 24)
                cap = min(self._RIGHT_PANEL_MAX_W, max_by_app)
                return max(self._RIGHT_PANEL_MIN_W, min(cap, w))
        except Exception:
            pass
        return max(self._RIGHT_PANEL_MIN_W, min(self._RIGHT_PANEL_MAX_W, w))

    def _set_right_panel_width(self, w: int, *, persist: bool = False) -> None:
        w = self._clamp_right_panel_width(w)
        try:
            rpc = self.query_one("#right_panel_container", Vertical)
            rpc.styles.width = w
        except Exception:
            return
        if persist:
            save = getattr(self.app, "_save_ui_preferences", None)
            if callable(save):
                save(right_panel_width=w)

    def _load_saved_right_panel_width(self) -> int | None:
        getter = getattr(self.app, "_get_ui_preference_path", None)
        if not callable(getter):
            return None
        try:
            path = getter()
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("right_panel_width")
            if raw is None:
                return None
            return int(raw)
        except Exception:
            return None

    def _apply_saved_right_panel_width(self) -> None:
        w = self._load_saved_right_panel_width()
        if w is None:
            return
        try:
            rpc = self.query_one("#right_panel_container", Vertical)
            if not rpc.display:
                return
        except Exception:
            return
        self._set_right_panel_width(w, persist=False)

    def on_right_panel_width_drag(self, event: RightPanelWidthDrag) -> None:
        self._set_right_panel_width(event.width, persist=False)

    def on_right_panel_width_commit(self, event: RightPanelWidthCommit) -> None:
        self._set_right_panel_width(event.width, persist=True)

    async def action_welcome_pick_session(self, session_id: str) -> None:
        """Switch session from welcome panel Recent activity (Rich ``@click``)."""
        await self.switch_session(session_id)

    def compose(self):
        """Compose the chat screen UI."""
        with Horizontal(id="chat_container"):
            yield Sidebar(id="sidebar")
            with Vertical(id="chat_area"):
                yield Static("", id="chat_status_bar")
                yield Vertical(id="message_list_host")
                # Keep input + HUD in one stack container for stable bottom layout.
                with Vertical(id="input_hud_stack"):
                    yield OpenCodeInput(id="opencode_input")
                    yield ClaudeCodeInput(id="claude_input")
                    yield MessageInput(id="message_input_widget")
                    yield HudBar("", id="bottom_status_bar")
            yield RightPanelGrip(id="right_panel_grip")
            with Vertical(id="right_panel_container"):
                yield InfoPanel(id="info_panel")
                yield PlanPanel(id="plan_panel")
                yield CodeAwarenessPanel(id="code_awareness_panel")

    def on_mount(self) -> None:
        """Called when the screen is mounted."""
        # Apply initial display mode ASAP (avoid first-frame flicker)
        try:
            app_mode = getattr(self.app, "display_mode", None)
            self._display_mode = str(
                app_mode or getattr(self.settings.tui, "display_mode", "opencode") or "opencode"
            ).lower()
            self._apply_display_mode(self._display_mode)
            self._focus_active_input()
        except Exception:
            pass

        self.call_later(self._apply_saved_right_panel_width)

        # Initialize services and create session
        asyncio.create_task(self._initialize())

    def on_unmount(self) -> None:
        """Stop background tasks owned by this screen."""
        monitor = self._code_awareness_monitor
        if monitor is not None:
            asyncio.create_task(monitor.stop())
            self._code_awareness_monitor = None
        if self._input_history_store is not None:
            self._input_history_store.save()
            self._input_history_store = None

    def _refresh_slash_skill_autocomplete(self) -> None:
        """Include plugin skill names (e.g. /api-design) in the `/` suggestion panel."""
        try:
            from ...plugin.slash import plugin_skill_autocomplete_entries

            pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None
            rows = plugin_skill_autocomplete_entries(pm)
            for w in self.query(MessageInput):
                w.set_slash_skill_autocomplete(rows)
        except Exception:
            pass

    def _get_run_state(self, session_id: str, *, create: bool = True) -> SessionRunState | None:
        if not session_id:
            return None
        state = self._session_runs.get(session_id)
        if state is None and create:
            state = SessionRunState(session_id=session_id)
            self._session_runs[session_id] = state
        return state

    def _get_ui_state(self, session_id: str, *, create: bool = True) -> SessionUiState | None:
        if not session_id:
            return None
        state = self._session_ui.get(session_id)
        if state is None and create:
            state = SessionUiState(session_id=session_id)
            self._session_ui[session_id] = state
        return state

    def _get_plan_state(self, session_id: str, *, create: bool = True) -> PlanSessionState | None:
        if not session_id:
            return None
        state = self._plan_state.get(session_id)
        if state is None and create:
            state = PlanSessionState(session_id=session_id)
            self._plan_state[session_id] = state
        return state

    def _hydrate_plan_state_from_disk(self, session_id: str) -> None:
        """Restore plan bundle from disk after cold start or when switching sessions."""
        if not self._plan_store or not session_id:
            return
        plan_state = self._get_plan_state(session_id, create=True)
        if plan_state is None or plan_state.bundle is not None:
            return
        bundle = self._plan_store.find_latest_bundle_for_session(session_id)
        if bundle is None:
            return
        if self._plan_store.normalize_stale_build_after_restart(bundle):
            self._plan_store.save_plan_bundle(bundle)
        plan_state.bundle = bundle
        plan_state.last_plan_path = bundle.markdown_path
        plan_state.last_plan_text = bundle.plan_text
        plan_state.last_user_request = bundle.user_request
        plan_state.mode = "plan_ready"
        self._sync_hud_todos_from_plan(plan_state)
        self._refresh_plan_panel(session_id)

    def _sync_hud_todos_from_plan(self, plan_state: PlanSessionState | None) -> None:
        if not plan_state or not plan_state.bundle:
            return
        todos: list[HudTodoItem] = []
        for t in plan_state.bundle.tasks:
            status = t.status if t.status in ("pending", "in_progress", "completed") else "pending"
            todos.append(HudTodoItem(content=t.title, status=status))  # type: ignore[arg-type]
        if todos:
            self._hud_todos = todos

    def _touch_plan_progress(self, session_id: str) -> None:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return
        bundle = plan_state.bundle
        if bundle.execution.current_task_index < 0:
            return
        bundle.execution.last_progress_at = int(time.time())
        bundle.execution.stall_count = 0
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)

    @classmethod
    def _stall_timeout_for_model(cls, model_name: str | None) -> int:
        lowered = (model_name or "").strip().lower()
        if not lowered:
            return cls._BUILD_STALL_TIMEOUT_S
        if (
            "reasoner" in lowered
            or "deepseek-r1" in lowered
            or "kimi-k2.5" in lowered
            or lowered.startswith("qwq")
            or "qvq" in lowered
            or lowered.startswith("minimax-")
            or "doubao-seed" in lowered
        ):
            return cls._BUILD_STALL_TIMEOUT_REASONER_S
        return cls._BUILD_STALL_TIMEOUT_S

    def _current_stall_timeout_seconds(self) -> int:
        model_name = ""
        try:
            agent_config = self.settings.get_agent_config("coder")
            model_name = str(getattr(agent_config, "model", "") or "")
        except Exception:
            model_name = ""
        return self._stall_timeout_for_model(model_name)

    def _force_release_run_lock(self, session_id: str) -> None:
        run_state = self._get_run_state(session_id, create=False)
        if run_state is None:
            return
        run_state.is_processing = False
        run_state.is_plan_run = False
        run_state.is_claw_run = False
        run_state.plan_user_request = ""
        run_state.build_task_index = -1
        run_state.task = None
        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.set_session_running(session_id, False)
            sidebar.set_session_waiting(session_id, False)
            self._refresh_sidebar_async()
        except Exception:
            pass
        self._stop_processing_indicator()

    def _handle_build_task_failure(
        self,
        session_id: str,
        task_index: int,
        reason: str,
        *,
        allow_auto_retry: bool = True,
    ) -> bool:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return False
        bundle = plan_state.bundle
        if not (0 <= task_index < len(bundle.tasks)):
            return False
        task_item = bundle.tasks[task_index]
        task_item.status = "failed"
        task_item.result_summary = (reason or "").strip()[:400]
        bundle.execution.last_error = (reason or "").strip()[:400]
        bundle.execution.current_task_index = task_index
        bundle.execution.last_progress_at = int(time.time())
        retry_key = task_item.id or f"task-{task_index + 1}"
        retries = int(bundle.execution.retry_count_by_task.get(retry_key, 0)) + 1
        bundle.execution.retry_count_by_task[retry_key] = retries

        should_retry = (
            allow_auto_retry
            and bool(bundle.execution.is_building)
            and retries <= self._BUILD_MAX_RETRIES_PER_TASK
        )
        if should_retry:
            task_item.status = "pending"
        else:
            bundle.execution.is_building = False
            bundle.execution.finished_at = int(time.time())
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        self._sync_hud_todos_from_plan(plan_state)
        self._refresh_plan_panel(session_id)
        # Do not call_later(_run_next_plan_task) here: this often runs while the
        # parent _process_message still has is_processing True, so _start_agent_run
        # would no-op. Chaining is done from _process_message's finally instead.
        return should_retry

    def _abort_active_build_run(
        self,
        session_id: str,
        *,
        reason: str,
        mark_failed: bool,
        interrupted: bool,
        allow_auto_retry: bool = False,
    ) -> bool:
        run_state = self._get_run_state(session_id, create=False)
        idx = int(run_state.build_task_index) if run_state is not None else -1
        auto_retry_scheduled = False
        if mark_failed and idx >= 0:
            auto_retry_scheduled = self._handle_build_task_failure(
                session_id,
                idx,
                reason,
                allow_auto_retry=allow_auto_retry,
            )
        plan_state = self._get_plan_state(session_id, create=False)
        if plan_state and plan_state.bundle:
            bundle = plan_state.bundle
            if interrupted and 0 <= idx < len(bundle.tasks):
                current_task = bundle.tasks[idx]
                if current_task.status == "in_progress":
                    current_task.status = "pending"
                    current_task.result_summary = (reason or "").strip()[:400]
            bundle.execution.interrupted = bool(interrupted)
            bundle.execution.last_error = (reason or "").strip()[:400]
            bundle.execution.last_progress_at = int(time.time())
            if interrupted:
                bundle.execution.is_building = False
                bundle.execution.finished_at = int(time.time())
            if self._plan_store:
                self._plan_store.save_plan_bundle(bundle)
            self._sync_hud_todos_from_plan(plan_state)
            self._refresh_plan_panel(session_id)

        if run_state and run_state.task is not None:
            try:
                run_state.task.cancel()
            except Exception:
                pass
        self._force_release_run_lock(session_id)
        # Watchdog/abort path can reset current task to pending while keeping the
        # build queue active (auto-retry). Since we force-release run lock above,
        # _process_message.finally will not chain next task for us; continue here.
        if mark_failed and allow_auto_retry and not interrupted:
            if plan_state and plan_state.bundle and plan_state.bundle.execution.is_building:
                self.call_later(lambda sid=session_id: self._run_next_plan_task(sid))
                return auto_retry_scheduled
        return auto_retry_scheduled

    @staticmethod
    def _extract_plan_title(plan_text: str, user_request: str = "") -> str:
        for line in (plan_text or "").splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("#"):
                text = text.lstrip("#").strip()
            if text:
                return text[:96]
        return (user_request or "Plan").strip()[:96] or "Plan"

    @staticmethod
    def _is_plan_build_completed(bundle: PlanBundle | None) -> bool:
        if bundle is None or not bundle.tasks:
            return False
        if bundle.execution.is_building:
            return False
        return all(t.status == "completed" for t in bundle.tasks)

    @staticmethod
    def _plan_execution_reconcile_inplace(bundle: PlanBundle) -> tuple[bool, bool]:
        """When every task is completed, normalize execution flags.

        Returns:
            (changed, show_build_completed_hint): ``changed`` if bundle fields were
            updated in memory; ``show_build_completed_hint`` if UI may emit a one-shot
            completion bubble (stale ``is_building`` while all tasks done).
        """
        if not bundle.tasks:
            return (False, False)
        if not all(t.status == "completed" for t in bundle.tasks):
            return (False, False)
        show_bubble = bool(bundle.execution.is_building)
        changed = False
        if bundle.execution.is_building:
            bundle.execution.is_building = False
            changed = True
        if bundle.execution.current_task_index != -1:
            bundle.execution.current_task_index = -1
            changed = True
        if bundle.execution.finished_at == 0:
            bundle.execution.finished_at = int(time.time())
            changed = True
        if changed:
            bundle.execution.interrupted = False
            bundle.execution.last_error = ""
        return (changed, show_bubble and changed)

    def _reconcile_plan_bundle_execution(self, session_id: str, bundle: PlanBundle) -> None:
        """Persist fixes when execution state disagrees with task statuses."""
        changed, show_completed_bubble = self._plan_execution_reconcile_inplace(bundle)
        if not changed:
            return
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        plan_state = self._get_plan_state(session_id, create=False)
        if plan_state is not None:
            self._sync_hud_todos_from_plan(plan_state)
        if show_completed_bubble and self.current_session_id == session_id:

            def _bubble() -> None:
                try:
                    ml = self._ensure_message_list(session_id)
                    plan_title = self._extract_plan_title(bundle.plan_text, bundle.user_request)
                    ml.start_assistant_message()
                    ml.update_content(f"{plan_title} [Build Completed]")
                    ml.finalize_message()
                except Exception:
                    pass

            self.call_later(_bubble)

    async def _recover_stale_plan_task_after_run(self, session_id: str, task_index: int) -> None:
        """If a build task stayed ``in_progress`` (no RESPONSE handler), finish or fail it."""
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return
        bundle = plan_state.bundle
        if not bundle.execution.is_building:
            return
        if not (0 <= task_index < len(bundle.tasks)):
            return
        if bundle.tasks[task_index].status != "in_progress":
            return

        assistant_text = ""
        if self._message_service:
            try:
                from ...message.service import MessageRole

                messages = await self._message_service.list_by_session(session_id, limit=200)
                for m in reversed(messages):
                    if m.role == MessageRole.ASSISTANT:
                        assistant_text = (m.content or "").strip()
                        break
            except Exception:
                assistant_text = ""

        if assistant_text:
            task_item = bundle.tasks[task_index]
            task_item.status = "completed"
            task_item.result_summary = assistant_text[:400]
            task_key = task_item.id or f"task-{task_index + 1}"
            bundle.execution.retry_count_by_task.pop(task_key, None)
            bundle.execution.last_error = ""
            bundle.execution.interrupted = False
            bundle.execution.last_progress_at = int(time.time())
            if self._plan_store:
                self._plan_store.save_plan_bundle(bundle)
            self._sync_hud_todos_from_plan(plan_state)
            self._refresh_plan_panel(session_id)
            return

        self._handle_build_task_failure(
            session_id,
            task_index,
            "Run ended without final response.",
            allow_auto_retry=True,
        )

    def _refresh_plan_panel(self, session_id: str) -> None:
        try:
            panel = self.query_one("#plan_panel", PlanPanel)
        except Exception:
            return
        plan_state = self._get_plan_state(session_id, create=False)
        run_state = self._get_run_state(session_id, create=False)
        can_build = False
        tasks: list[PlanTaskItem] = []
        is_building = False
        current_index = -1
        title = "No plan"
        is_completed = False
        show_panel = False
        can_stop = False
        can_retry_current = False
        can_resume = False
        status_text = ""
        if plan_state and plan_state.bundle:
            bundle = plan_state.bundle
            self._reconcile_plan_bundle_execution(session_id, bundle)
            tasks = bundle.tasks
            is_building = bool(bundle.execution.is_building)
            current_index = int(bundle.execution.current_task_index)
            is_completed = self._is_plan_build_completed(bundle)
            title = self._extract_plan_title(bundle.plan_text, bundle.user_request)
            can_build = (not is_building) and bool(tasks) and not bool(run_state and run_state.is_processing)
            show_panel = bool(tasks) and (is_building or not is_completed)
            has_unfinished = any(t.status in ("pending", "failed", "in_progress") for t in tasks)
            has_failed = any(t.status == "failed" for t in tasks)
            can_stop = bool(run_state and run_state.is_processing and is_building)
            can_retry_current = (
                not bool(run_state and run_state.is_processing)
                and 0 <= current_index < len(tasks)
                and tasks[current_index].status in ("failed", "in_progress")
            )
            can_resume = (
                not bool(run_state and run_state.is_processing)
                and not is_building
                and has_unfinished
            )
            if is_building:
                status_text = "Running"
            elif bundle.execution.interrupted:
                status_text = "Interrupted"
            elif has_failed and not is_completed:
                status_text = "Awaiting retry"
            elif int(bundle.execution.stall_count or 0) > 0 and has_unfinished:
                status_text = "Stalled"
            elif is_completed:
                status_text = "Build completed"
            else:
                status_text = "Ready to build"
        panel.display = show_panel
        running_task_title = ""
        if (
            tasks
            and is_building
            and 0 <= current_index < len(tasks)
        ):
            running_task_title = (tasks[current_index].title or "").strip()

        panel.set_plan(
            title=title,
            todo_count=len(tasks),
            tasks=tasks,
            is_building=is_building,
            current_task_index=current_index,
            can_build=can_build,
            is_completed=is_completed,
            can_stop=can_stop,
            can_retry_current=can_retry_current,
            can_resume=can_resume,
            status_text=status_text,
            running_task_title=running_task_title,
        )

    def _message_list_host(self) -> Vertical:
        return self.query_one("#message_list_host", Vertical)

    def _ensure_message_list(self, session_id: str) -> MessageList:
        ui_state = self._get_ui_state(session_id)
        assert ui_state is not None
        if ui_state.message_list is not None:
            return ui_state.message_list

        host = self._message_list_host()
        host.styles.height = "1fr"
        host.styles.width = "1fr"
        widget_id = f"message_list_{session_id.replace('-', '_')}"
        message_list = MessageList(id=widget_id)
        message_list.styles.height = "1fr"
        message_list.styles.width = "1fr"
        ui_state.message_list = message_list
        host.mount(message_list)
        message_list.display = False
        # MessageList is created lazily after the first _apply_display_mode_chrome pass
        # (on_mount / _initialize run before any list exists). Re-run chrome so scrollbar
        # thumb/track match the active display mode instead of the global Textual theme.
        try:
            self._apply_display_mode_chrome(self._display_mode)
        except Exception:
            pass
        return message_list

    def _ui_display_version(self) -> str:
        """Version text shown in TUI surfaces.

        Priority:
        1) `.clawcode.json` -> `tui.display_version` (when non-empty)
        2) installed package version
        3) "dev"
        """
        try:
            tui_cfg = getattr(self.settings, "tui", None)
            cfg_val = str(getattr(tui_cfg, "display_version", "") or "").strip()
            if cfg_val:
                return cfg_val
        except Exception:
            pass
        try:
            from importlib.metadata import version

            return version("clawcode")
        except Exception:
            return "dev"

    async def _build_welcome_context(self, session_id: str):
        """Gather model, workspace hint, recent sessions, and theme for the welcome panel."""
        from pathlib import Path

        from ...config.constants import AgentName
        from ..styles.display_mode_styles import resolve_chrome
        from ..welcome_banner import (
            RecentSessionItem,
            WelcomeContext,
            welcome_style_from_chrome,
        )

        chrome = resolve_chrome(self._display_mode)
        style = welcome_style_from_chrome(chrome)
        try:
            ac = self.settings.get_agent_config(AgentName.CODER)
            model_label = (ac.model or "unknown").strip()
        except Exception:
            model_label = "unknown"

        wd = str(getattr(self.settings, "working_directory", None) or "").strip() or "."
        hint = _hud_project_hint(wd)
        if not hint:
            try:
                p = Path(wd).expanduser()
                hint = str(p)
                if len(hint) > 52:
                    hint = "..." + hint[-49:]
            except Exception:
                hint = wd[:52]

        recent_items: list[RecentSessionItem] = []
        try:
            if self._session_service:
                sessions = await self._session_service.list(limit=16)
                for s in sessions:
                    if s.id == session_id:
                        continue
                    t = (s.title or "").strip() or (s.id[:12] + "..." if len(s.id) > 12 else s.id)
                    recent_items.append(RecentSessionItem(session_id=s.id, title=t))
                    if len(recent_items) >= 5:
                        break
        except Exception:
            pass

        return WelcomeContext(
            version=self._ui_display_version(),
            model_label=model_label,
            workspace_hint=hint,
            style=style,
            recent_session_items=recent_items,
            mascot_variant=(
                "simple" if self._display_mode in {"minimal", "zen"} else "cartoon"
            ),
            announcement="Tip: prefer view / ls / glob / grep over raw shell when exploring.",
        )

    async def _show_session_message_list(self, session_id: str, *, force_reload: bool = False) -> MessageList:
        ui_state = self._get_ui_state(session_id)
        assert ui_state is not None
        message_list = self._ensure_message_list(session_id)

        for sid, other_state in self._session_ui.items():
            if other_state.message_list is not None:
                other_state.message_list.display = sid == session_id

        if force_reload or not ui_state.history_loaded:
            message_list.clear()
            messages = await self._message_service.list_by_session(session_id)
            if messages:
                self._render_history_messages(messages, message_list)
            else:
                message_list.add_welcome_message(
                    context=await self._build_welcome_context(session_id),
                )
            ui_state.history_loaded = True

        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.set_session_unread(session_id, False)
        run_state = self._get_run_state(session_id, create=False)
        if run_state is not None:
            run_state.has_unread_output = False
        self._refresh_plan_panel(session_id)
        return message_list

    def _mark_session_unread(self, session_id: str) -> None:
        if not session_id or session_id == self.current_session_id:
            return
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.set_session_unread(session_id, True)
        run_state = self._get_run_state(session_id, create=True)
        if run_state is not None:
            run_state.has_unread_output = True

    def _refresh_sidebar_async(self) -> None:
        self._sidebar_refresh_pending = True
        if self._sidebar_refresh_task is not None and not self._sidebar_refresh_task.done():
            return

        async def _drain_sidebar_refresh() -> None:
            try:
                while self._sidebar_refresh_pending:
                    self._sidebar_refresh_pending = False
                    try:
                        sidebar = self.query_one("#sidebar", Sidebar)
                        await sidebar.refresh_sessions()
                    except Exception:
                        # Sidebar may be unmounted during app/screen transitions.
                        return
                    # Yield once so concurrent requests can be coalesced.
                    await asyncio.sleep(0)
            finally:
                self._sidebar_refresh_task = None

        self._sidebar_refresh_task = asyncio.create_task(_drain_sidebar_refresh())

    def set_session_waiting(self, session_id: str, waiting: bool) -> None:
        run_state = self._get_run_state(session_id, create=True)
        if run_state is not None:
            run_state.waiting_permission = waiting
        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.set_session_waiting(session_id, waiting)
            self._refresh_sidebar_async()
        except Exception:
            pass

    async def _rebuild_llm_stack(self) -> None:
        """Recreate LLM provider, tools, and Agent from current ``settings`` (e.g. after Ctrl+O switch)."""
        from ...llm.runtime_bundle import build_coder_runtime

        if not getattr(self, "_session_service", None) or not getattr(self, "_message_service", None):
            return

        lsp_mgr = getattr(self._app_context, "lsp_manager", None) if self._app_context else None
        pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None

        _for_claw: bool | None = None
        if getattr(self.settings.desktop, "tools_require_claw_mode", False):
            _for_claw = bool(getattr(self, "_claw_mode_enabled", False))

        bundle = build_coder_runtime(
            settings=self.settings,
            session_service=self._session_service,
            message_service=self._message_service,
            permissions=self.app,
            plugin_manager=pm,
            lsp_manager=lsp_mgr,
            for_claw_mode=_for_claw,
            style="tui_coder",
        )
        self._agent = bundle.make_claw_agent(permission_client=self.app)

    async def _initialize(self) -> None:
        """Initialize the chat screen with services (from AppContext or create locally)."""
        try:
            from ...llm.plan_store import PlanStore
            from ...storage_paths import ensure_primary_root

            if self._app_context:
                self._session_service = self._app_context.session_service
                self._message_service = self._app_context.message_service
            else:
                from ...db import get_database
                from ...message import MessageService
                from ...session import SessionService

                db = get_database()
                self._session_service = SessionService(db)
                self._message_service = MessageService(db)

            # Prefer reusing the most recently updated session
            existing_sessions = await self._session_service.list(limit=1)
            if existing_sessions:
                session = existing_sessions[0]
            else:
                session = await self._session_service.create("New Chat")

            self.current_session_id = session.id
            self._current_session_title = session.title
            wd = str(getattr(self.settings, "working_directory", None) or "").strip() or "."
            ensure_primary_root(wd)
            self._plan_store = PlanStore(wd)
            self._get_plan_state(session.id, create=True)
            self._hydrate_plan_state_from_disk(session.id)

            # Initial display mode (from App preference or settings default).
            # Guard: only re-apply if the resolved mode differs from what on_mount()
            # already applied, to avoid a redundant chrome repaint + full layout pass.
            app_mode = getattr(self.app, "display_mode", None)
            resolved_mode = str(app_mode or getattr(self.settings.tui, "display_mode", "opencode") or "opencode").lower()
            if resolved_mode != self._display_mode:
                self._display_mode = resolved_mode
                self._apply_display_mode(self._display_mode)

            # Wire sidebar and refresh
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.set_session_service(self._session_service)
            sidebar.set_selected_session(self.current_session_id)
            await sidebar.refresh_sessions()

            await self._show_session_message_list(
                self.current_session_id,
                force_reload=True,
            )

            lsp_mgr = getattr(self._app_context, "lsp_manager", None) if self._app_context else None
            pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None

            # HUD static config counts (CLAUDE.md/rules/MCPs/hooks) - best-effort.
            self._hud_plugin_manager = pm
            try:
                from pathlib import Path

                wd = str(getattr(self.settings, "working_directory", None) or "").strip() or "."
                p = Path(wd).expanduser()
                try:
                    p = p.resolve()
                except Exception:
                    pass

                # Walk up a few levels to find a likely project root.
                root = p
                for _ in range(6):
                    if _has_hud_rule_signals(root):
                        break
                    if root.parent == root:
                        break
                    root = root.parent

                self._hud_project_dir = str(root)
                self._hud_counts = count_configs(self._hud_project_dir, plugin_manager=pm)
            except Exception:
                pass

            # Reset per-session HUD dynamic state.
            self._hud_tool_counts.clear()
            self._hud_agent_entries.clear()
            self._hud_running_tools.clear()

            await self._rebuild_llm_stack()

            # Focus the input and update status bar
            self._focus_active_input()
            await self._sync_session_metrics()
            self._update_status_bars()
            await self._update_info_panel()
            self._refresh_slash_skill_autocomplete()
            await self._init_code_awareness()
            self._init_input_history()
        except Exception as e:
            # Surface initialization errors both in UI and logs
            try:
                if self.current_session_id:
                    message_list = self._ensure_message_list(self.current_session_id)
                    message_list.display = True
                else:
                    message_list = self._ensure_message_list("init_error")
                    message_list.display = True
                message_list.add_error(f"Init error: {e}")
            except Exception:
                pass

    async def _sync_session_metrics(self) -> None:
        """Load token/cost metrics for current session (best-effort)."""
        if not getattr(self, "_session_service", None) or not self.current_session_id:
            self._session_prompt_tokens = 0
            self._session_completion_tokens = 0
            self._session_cost = 0.0
            self._hud_turn_input_tokens = 0
            self._hud_turn_output_tokens = 0
            self._hud_turn_output_chars = 0
            return
        try:
            sess = await self._session_service.get(self.current_session_id)
            if not sess:
                return
            self._session_prompt_tokens = int(getattr(sess, "prompt_tokens", 0) or 0)
            self._session_completion_tokens = int(getattr(sess, "completion_tokens", 0) or 0)
            self._session_cost = float(getattr(sess, "cost", 0.0) or 0.0)
            self._hud_turn_input_tokens = 0
            self._hud_turn_output_tokens = 0
            self._hud_turn_output_chars = 0
        except Exception:
            pass

    def _format_compact_tokens(self, total_tokens: int) -> str:
        """Format token count compactly (e.g. 1.2K, 3.5M)."""
        tok = int(total_tokens or 0)
        if tok >= 1_000_000:
            return f"{tok/1_000_000:.1f}M"
        if tok >= 1_000:
            return f"{tok/1_000:.1f}K"
        return str(tok)

    def _format_tokens_and_cost(self, total_tokens: int, cost: float) -> str:
        # Format: "Context: 12.9K, Cost: $0.05"
        tok = int(total_tokens or 0)
        if tok >= 1_000_000:
            t_str = f"{tok/1_000_000:.1f}M"
        elif tok >= 1_000:
            t_str = f"{tok/1_000:.1f}K"
        else:
            t_str = str(tok)
        if t_str.endswith(".0K"):
            t_str = t_str.replace(".0K", "K")
        if t_str.endswith(".0M"):
            t_str = t_str.replace(".0M", "M")
        return f"Context: {t_str}, Cost: ${cost:.2f}"

    def _compute_diagnostics_summary(self) -> str:
        lsp_mgr = getattr(self._app_context, "lsp_manager", None) if self._app_context else None
        if not lsp_mgr:
            return "No diagnostics"
        clients = getattr(lsp_mgr, "_clients", {}) or {}
        err = warn = hint = info = 0
        try:
            for _, client in clients.items():
                diags_map = client.get_diagnostics()  # type: ignore[call-arg]
                if isinstance(diags_map, dict):
                    for _, diags in diags_map.items():
                        for d in diags or []:
                            sev = getattr(d, "severity", None)
                            if sev in (1, "error", "Error"):
                                err += 1
                            elif sev in (2, "warning", "Warning"):
                                warn += 1
                            elif sev in (3, "information", "info", "Information"):
                                info += 1
                            elif sev in (4, "hint", "Hint"):
                                hint += 1
        except Exception:
            return "No diagnostics"
        parts: list[str] = []
        if err:
            parts.append(f"E {err}")
        if warn:
            parts.append(f"! {warn}")
        if hint:
            parts.append(f". {hint}")
        if info:
            parts.append(f"i {info}")
        return " ".join(parts) if parts else "No diagnostics"

    def _update_status_bars(self, *, refresh_hud: bool = True) -> None:
        """Update top and bottom status bars (CSS decides which is visible).

        When ``refresh_hud`` is False, only the classic top bar is refreshed ????used by the
        processing spinner timer so the multi-line HUD is not repainted every 200ms
        (reduces flicker / jitter).
        """
        try:
            bar = self.query_one("#chat_status_bar", Static)

            # Session title: keep tail for long titles.
            session_label = self._current_session_title or self.current_session_id or "New session"
            if len(session_label) > 24:
                session_label = "..." + session_label[-23:]

            agent_config = self.settings.get_agent_config("coder")
            model = agent_config.model

            # Provider derived from model name (fallback to anthropic)
            provider = "anthropic"
            lower_model = (model or "").lower()
            if "gpt" in lower_model or "openai" in lower_model:
                provider = "openai"
            elif "gemini" in lower_model:
                provider = "gemini"

            # Working directory shown in status bar
            cwd = getattr(self.settings, "working_directory", "") or ""
            if len(cwd) > 40:
                cwd = "..." + cwd[-39:]

            app_version = self._ui_display_version()

            # Auto-compact + LSP status
            auto_compact = getattr(self.settings, "auto_compact", True)
            compact_str = "compact" if auto_compact else "no-compact"
            lsp_mgr = getattr(self._app_context, "lsp_manager", None) if self._app_context else None
            lsp_str = "LSP:on" if lsp_mgr else "LSP:off"

            mouse_str = ""
            try:
                app = getattr(self, "app", None)
                if app and hasattr(app, "is_mouse_mode_enabled"):
                    mouse_str = "  mouse:" + ("ON" if app.is_mouse_mode_enabled() else "OFF")
            except Exception:
                mouse_str = ""

            processing_str = ""
            run_state = self._get_run_state(self.current_session_id or "", create=False)
            if run_state and run_state.is_processing:
                frames = ["|", "/", "-", "\\"]
                processing_str = f"  {frames[run_state.spinner_frame % len(frames)]} working"

            bar.update(
                f"ClawCode v{app_version}  cwd: {cwd}  Session: {session_label}  "
                f"Model: {model} ({provider})  {compact_str}  {lsp_str}{mouse_str}{processing_str}"
            )
        except Exception:
            pass

        if not refresh_hud:
            return

        try:
            bottom = self.query_one("#bottom_status_bar", HudBar)

            agent_config = self.settings.get_agent_config("coder")
            model = agent_config.model or "Unknown"

            db_total = int(self._session_prompt_tokens + self._session_completion_tokens)
            live_total = self._hud_turn_input_tokens + self._hud_turn_output_tokens
            if live_total == 0 and self._hud_turn_output_chars > 0:
                live_total = db_total + int(self._hud_turn_output_chars * 1.5)
            total_tokens = max(db_total, live_total)
            ctx_window_size = get_context_window_size(model)
            context_percent = 0
            if ctx_window_size > 0:
                context_percent = min(100, int(round((total_tokens / ctx_window_size) * 100)))

            run_state = self._get_run_state(self.current_session_id or "", create=False)
            session_duration = ""
            if run_state:
                if run_state.is_processing:
                    seconds = max(0.0, time.monotonic() - float(run_state.started_at or 0.0))
                    session_duration = format_hud_session_duration(seconds)
                elif run_state.last_turn_duration_str:
                    session_duration = run_state.last_turn_duration_str

            agent_entries = sorted(
                self._hud_agent_entries.values(), key=lambda a: a.start_time
            )[-self._hud_max_agent_entries :]

            hud_dir = self._hud_project_dir or str(getattr(self.settings, "working_directory", None) or "").strip() or "."
            project_hint = _hud_project_hint(hud_dir)

            # If plugin_manager isn't ready at init time, lazily refresh counts (throttled).
            try:
                pm = self._hud_plugin_manager
                now = time.monotonic()
                all_zero = (
                    self._hud_counts.claude_md_count == 0
                    and self._hud_counts.rules_count == 0
                    and self._hud_counts.mcp_count == 0
                    and self._hud_counts.hooks_count == 0
                )
                if all_zero and pm is not None and (now - self._hud_counts_last_refresh) >= self._hud_counts_refresh_interval_s:
                    self._hud_counts_last_refresh = now
                    root_dir = self._hud_project_dir or self.settings.working_directory
                    self._hud_counts = count_configs(root_dir, plugin_manager=pm)
            except Exception:
                pass

            # Build deep_loop HUD status string when a loop is active.
            deep_loop_status = ""
            _dl = self._clawteam_loop_store().get(self.current_session_id or "")
            if isinstance(_dl, dict):
                dl_iter  = int(_dl.get("iter_idx", 1) or 1)
                dl_max   = int(_dl.get("max_iters", 100) or 100)
                dl_stall = int(_dl.get("stall_count", 0) or 0)
                dl_last  = float(_dl.get("last_activity_at") or 0.0)
                idle_s   = max(0.0, time.monotonic() - dl_last) if dl_last else 0.0
                is_running = run_state is not None and run_state.is_processing
                icon = "◐" if is_running else "○"
                stall_suffix = f" | 自动恢复×{dl_stall}" if dl_stall > 0 else ""
                idle_suffix  = "" if is_running else f" | 等待 {int(idle_s)}s"
                deep_loop_status = f"{icon} 深度循环 迭代 {dl_iter}/{dl_max}{stall_suffix}{idle_suffix}"

            state = HudState(
                model=model,
                context_percent=context_percent,
                context_window_size=ctx_window_size,
                config_counts=self._hud_counts,
                session_duration=session_duration,
                project_hint=project_hint,
                tool_counts=dict(self._hud_tool_counts),
                running_tools=list(self._hud_running_tools.values()),
                agent_entries=agent_entries,
                todos=list(self._hud_todos),
                deep_loop_status=deep_loop_status,
            )
            from ..hud.render import HudColors
            from ..styles.display_mode_styles import resolve_chrome
            ch = resolve_chrome(self._display_mode)
            hud_c = HudColors(
                model=ch.hud_model_color,
                tool_running=ch.hud_tool_running_color,
                tool_name=ch.hud_tool_name_color,
                tool_done=ch.hud_tool_done_color,
                agent_type=ch.hud_agent_type_color,
                todo_bullet=ch.hud_todo_bullet_color,
            )
            now_mono = time.monotonic()
            bottom.set_state(state, now=now_mono, colors=hud_c)
            if self.current_session_id:
                if (now_mono - self._last_plan_panel_refresh_at) >= self._PLAN_PANEL_REFRESH_MIN_INTERVAL_S:
                    self._last_plan_panel_refresh_at = now_mono
                    self._refresh_plan_panel(self.current_session_id)
        except Exception:
            pass

    def _mark_hud_dirty(self) -> None:
        """Mark HUD as needing a refresh; schedules a single lazy flush via call_later.

        Replaces direct _update_status_bars() calls in hot paths (USAGE, CONTENT_DELTA,
        TOOL_USE, TOOL_RESULT) to batch multiple rapid agent events into one repaint.
        """
        if self._hud_dirty:
            return  # flush already queued
        self._hud_dirty = True
        self.call_later(self._flush_hud_if_dirty)

    def _flush_hud_if_dirty(self) -> None:
        """Consume the pending HUD dirty flag and repaint the status bars."""
        if not self._hud_dirty:
            return
        self._hud_dirty = False
        self._update_status_bars()

    def _start_processing_indicator(self) -> None:
        if self._processing_timer is not None:
            return

        def _tick() -> None:
            now = time.monotonic()
            for state in self._session_runs.values():
                if state.is_processing:
                    state.spinner_frame += 1
            if now - self._last_build_watchdog_check >= self._BUILD_WATCHDOG_INTERVAL_S:
                self._last_build_watchdog_check = now
                self._run_build_watchdog()
            self._update_status_bars(refresh_hud=False)

        # Keep status bar spinner updated while processing.
        self._processing_timer = self.set_interval(0.2, _tick)

    def _run_build_watchdog(self) -> None:
        now_ts = int(time.time())
        stall_timeout_s = self._current_stall_timeout_seconds()
        for session_id, run_state in list(self._session_runs.items()):
            if not run_state.is_processing or run_state.build_task_index < 0:
                continue
            plan_state = self._get_plan_state(session_id, create=False)
            if not plan_state or not plan_state.bundle:
                continue
            bundle = plan_state.bundle
            if not bundle.execution.is_building:
                continue
            last_progress = int(bundle.execution.last_progress_at or 0)
            if last_progress <= 0:
                bundle.execution.last_progress_at = now_ts
                if self._plan_store:
                    self._plan_store.save_plan_bundle(bundle)
                continue
            if now_ts - last_progress < stall_timeout_s:
                continue
            bundle.execution.stall_count = int(bundle.execution.stall_count or 0) + 1
            if int(bundle.execution.stall_count or 0) <= self._BUILD_STALL_GRACE_COUNT:
                # First stall window is a soft mark for long-thinking models.
                bundle.execution.last_progress_at = now_ts
                if self._plan_store:
                    self._plan_store.save_plan_bundle(bundle)
                continue
            if self._plan_store:
                self._plan_store.save_plan_bundle(bundle)
            auto_retry_scheduled = self._abort_active_build_run(
                session_id,
                reason="Task stalled: no progress for too long.",
                mark_failed=True,
                interrupted=False,
                allow_auto_retry=True,
            )
            if auto_retry_scheduled:
                continue
            try:
                message_list = self._ensure_message_list(session_id)
                message_list.add_error(
                    "Build task stalled and exceeded auto-retry limit. Use Retry or Resume (scroll the button row if needed)."
                )
            except Exception:
                pass

    def _stop_processing_indicator(self) -> None:
        if any(state.is_processing for state in self._session_runs.values()):
            self._update_status_bars()
            return
        if self._processing_timer is None:
            return
        try:
            self._processing_timer.stop()
        except Exception:
            pass
        self._processing_timer = None
        for state in self._session_runs.values():
            state.spinner_frame = 0
        self._update_status_bars()

    # ------------------------------------------------------------------
    # Deep-loop background monitor
    # ------------------------------------------------------------------

    def _start_deep_loop_monitor(self) -> None:
        """Start the dedicated deep_loop watchdog timer (idempotent)."""
        if self._deep_loop_monitor_timer is not None:
            return
        if not getattr(self, "is_mounted", False):
            # Unit tests construct ChatScreen without mounting; avoid dangling Timer coroutines.
            return
        try:
            self._deep_loop_monitor_timer = self.set_interval(
                self._DEEP_LOOP_MONITOR_INTERVAL_S, self._run_deep_loop_watchdog
            )
        except RuntimeError:
            # No running loop: deep loop still works without watchdog.
            self._deep_loop_monitor_timer = None

    def _stop_deep_loop_monitor(self) -> None:
        """Stop the deep_loop watchdog timer only when no loops remain active."""
        if self._deep_loop_monitor_timer is None:
            return
        if self._clawteam_deep_loop_state:
            return  # other sessions still have active loops
        try:
            self._deep_loop_monitor_timer.stop()
        except Exception:
            pass
        self._deep_loop_monitor_timer = None

    def _run_deep_loop_watchdog(self) -> None:
        """Periodic watchdog: detect stalled deep_loops and auto-restart them.

        Called every _DEEP_LOOP_MONITOR_INTERVAL_S seconds by the dedicated timer.
        For each active deep_loop session:
        - If the agent is still running, update last_activity_at and skip.
        - If the loop has been idle longer than _DEEP_LOOP_STALL_TIMEOUT_S and the
          agent is NOT processing, treat the loop as stalled.
        - Auto-restart up to _DEEP_LOOP_MAX_STALLS times; give up thereafter.
        """
        now = time.monotonic()
        for sid, state in list(self._clawteam_deep_loop_state.items()):
            if not isinstance(state, dict):
                continue
            run_state = self._get_run_state(sid, create=False)
            if run_state is not None and run_state.is_processing:
                # Agent is actively running this session's iteration; not stalled.
                state["last_activity_at"] = now
                continue
            last_activity = float(state.get("last_activity_at") or 0.0)
            idle_s = (now - last_activity) if last_activity else 0.0
            if idle_s < self._DEEP_LOOP_STALL_TIMEOUT_S:
                continue
            # Loop appears stalled.
            stall_count = int(state.get("stall_count", 0) or 0)
            if stall_count >= self._DEEP_LOOP_MAX_STALLS:
                self._append_clawteam_deep_loop_log(
                    sid,
                    f"[clawteam deep_loop] 自动恢复已达上限（{stall_count} 次），放弃循环。",
                )
                self._clawteam_loop_store().pop(sid, None)
                self._clawteam_last_response_store().pop(sid, None)
                self._stop_deep_loop_monitor()
                continue
            state["stall_count"] = stall_count + 1
            state["last_activity_at"] = now  # reset to avoid re-triggering next tick
            self._append_clawteam_deep_loop_log(
                sid,
                f"[clawteam deep_loop] 检测到循环中断（闲置 {int(idle_s)}s），"
                f"自动恢复第 {stall_count + 1}/{self._DEEP_LOOP_MAX_STALLS} 次。",
            )
            self._continue_clawteam_deep_loop_if_needed(sid)
        self._update_status_bars()  # refresh HUD idle counter

    async def switch_session(self, session_id: str) -> None:
        """Switch to another session and load its messages."""
        if not self._session_service or not self._message_service:
            return
        # Archive code awareness modified files for the old session
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
            old_sid = self.current_session_id
            if old_sid:
                cap._state.session_modified_files[old_sid] = set(cap._state.modified_files)
                cap._state.session_read_files[old_sid] = set(cap._state.read_files)
                cap._state.session_modification_events[old_sid] = list(cap._state.modification_events)
                cap._state.session_read_events[old_sid] = list(cap._state.read_events)
                cap._state.session_file_events[old_sid] = list(cap._state.file_events)
            # Restore or clear for new session
            cap.restore_session_file_marks(
                modified_files=cap._state.session_modified_files.get(session_id, set()),
                read_files=cap._state.session_read_files.get(session_id, set()),
                modification_events=cap._state.session_modification_events.get(session_id, []),
                read_events=cap._state.session_read_events.get(session_id, []),
            )
            cap.set_file_events(cap._state.session_file_events.get(session_id, []))
            cap.set_active_session(session_id)
        except Exception:
            pass
        self._switch_generation += 1
        switch_generation = self._switch_generation
        self.current_session_id = session_id
        # Switching session => clear HUD dynamic counters.
        self._hud_tool_counts.clear()
        self._hud_agent_entries.clear()
        self._hud_todos.clear()
        self._hud_task_id_to_index.clear()
        self._hud_running_tools.clear()
        self._hud_turn_input_tokens = 0
        self._hud_turn_output_tokens = 0
        self._hud_turn_output_chars = 0
        self._hydrate_plan_state_from_disk(session_id)
        try:
            self.app.current_session_id = session_id
        except Exception:
            pass
        sess = await self._session_service.get(session_id)
        if switch_generation != self._switch_generation:
            return
        self._current_session_title = sess.title if sess else None
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.set_selected_session(session_id)
        sidebar.set_session_unread(session_id, False)
        await sidebar.refresh_sessions()
        await self._show_session_message_list(session_id)
        if switch_generation != self._switch_generation:
            return
        await self._sync_session_metrics()
        self._update_status_bars()
        await self._update_info_panel()

    def remove_session_ui(self, session_id: str) -> None:
        """Remove cached UI/runtime state for a deleted session."""
        ui_state = self._session_ui.pop(session_id, None)
        if ui_state and ui_state.message_list is not None:
            try:
                ui_state.message_list.remove()
            except Exception:
                pass
        run_state = self._session_runs.pop(session_id, None)
        if run_state and run_state.task and not run_state.task.done():
            run_state.task.cancel()

    def _focus_active_input(self) -> None:
        """Focus whichever input widget is active for current display mode."""
        try:
            if self._display_mode == "classic":
                w = self.query_one("#message_input_widget", MessageInput)
            elif self._display_mode == "claude":
                w = self.query_one("#claude_input", ClaudeCodeInput)
            else:
                w = self.query_one("#opencode_input", OpenCodeInput)
            w.focus()
        except Exception:
            pass

    def _get_active_input(self) -> MessageInput:
        """Return the input widget that is active for current mode."""
        if self._display_mode == "classic":
            return self.query_one("#message_input_widget", MessageInput)
        if self._display_mode == "claude":
            return self.query_one("#claude_input", ClaudeCodeInput)
        return self.query_one("#opencode_input", OpenCodeInput)

    def _apply_display_mode_chrome(self, mode: str) -> None:
        """Apply per-mode shell colors and conversation Rich palette; refresh lists.

        Skips the expensive refresh_message_lists_on_screen() call when the same
        chrome mode is re-applied (e.g. on_mount then _initialize with identical mode).
        """
        from ..styles.display_mode_styles import resolve_chrome

        set_conversation_style_for_mode(mode)
        chrome = resolve_chrome(mode)

        # Store on App so dialogs and other screens can read it
        try:
            self.app._display_chrome = chrome  # type: ignore[attr-defined]
        except Exception:
            pass

        # --- Screen / Header / Footer (ancestors ????can't use CSS descendant) ---
        try:
            self.screen.styles.background = chrome.message_list_bg
        except Exception:
            pass
        try:
            for h in self.app.query("Header"):
                h.styles.background = chrome.bottom_status_bg
            for h in self.app.query("Header.-tint"):
                h.styles.background = chrome.bottom_status_bg
        except Exception:
            pass
        try:
            for f in self.app.query("Footer"):
                f.styles.background = chrome.bottom_status_bg
        except Exception:
            pass

        # --- Chat container ---
        try:
            cc = self.query_one("#chat_container", Horizontal)
            if chrome.chat_container_bg:
                cc.styles.background = chrome.chat_container_bg
            else:
                cc.styles.clear_rule("background")
        except Exception:
            pass

        try:
            sb = self.query_one("#sidebar", Sidebar)
            sb.styles.background = chrome.sidebar_bg
            sb.styles.border_right = ("round", chrome.sidebar_border_color)
            for h in sb.query(".header"):
                h.styles.color = chrome.sidebar_header_color
        except Exception:
            pass

        try:
            top = self.query_one("#chat_status_bar", Static)
            top.styles.background = chrome.chat_status_bg
            top.styles.color = chrome.chat_status_color
        except Exception:
            pass

        try:
            bottom = self.query_one("#bottom_status_bar", HudBar)
            bottom.styles.background = chrome.bottom_status_bg
            bottom.styles.color = chrome.bottom_status_color
        except Exception:
            pass

        try:
            rpc = self.query_one("#right_panel_container", Vertical)
            rpc.styles.background = chrome.info_panel_bg
            rpc.styles.border_left = ("thick", chrome.info_panel_border_left_color)
        except Exception:
            pass

        try:
            grip = self.query_one("#right_panel_grip", RightPanelGrip)
            grip.styles.background = chrome.info_panel_bg
            grip.styles.border_right = ("tall", chrome.info_panel_border_left_color)
        except Exception:
            pass

        try:
            info = self.query_one("#info_panel", InfoPanel)
            info.styles.background = chrome.info_panel_bg
            info.styles.color = chrome.info_panel_color
        except Exception:
            pass

        try:
            plan_panel = self.query_one("#plan_panel", PlanPanel)
            plan_panel.styles.background = chrome.info_panel_bg
            plan_panel.styles.color = chrome.info_panel_color
        except Exception:
            pass

        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
            cap.styles.background = chrome.info_panel_bg
            cap.styles.color = chrome.info_panel_color
            hl = getattr(chrome, "code_awareness_highlight_color", None) or chrome.hud_tool_done_color
            read_hl = getattr(chrome, "code_awareness_read_highlight_color", None) or "#7eb8da"
            from ..styles.display_mode_styles import resolve_chat
            chat_s = resolve_chat(mode)
            cap.set_colors(
                accent=chat_s.accent,
                muted=chrome.info_panel_color,
                highlight=hl,
                read_highlight=read_hl,
            )
            # Same scrollbar thumb/track as MessageList / display-mode modal (ScrollBar reads parent)
            if chrome.scrollbar_thumb_color:
                cap.styles.scrollbar_color = chrome.scrollbar_thumb_color
                cap.styles.scrollbar_color_hover = chrome.scrollbar_thumb_color
                cap.styles.scrollbar_color_active = chrome.scrollbar_thumb_color
                cap_track = chrome.scrollbar_track_color or chrome.info_panel_bg
                cap.styles.scrollbar_background = cap_track
                cap.styles.scrollbar_background_hover = cap_track
                cap.styles.scrollbar_background_active = cap_track
            else:
                for key in (
                    "scrollbar_color",
                    "scrollbar_color_hover",
                    "scrollbar_color_active",
                    "scrollbar_background",
                    "scrollbar_background_hover",
                    "scrollbar_background_active",
                ):
                    cap.styles.clear_rule(key)
        except Exception:
            pass

        for wid in ("#opencode_input", "#claude_input", "#message_input_widget"):
            try:
                row = self.query_one(wid)
                row.styles.background = chrome.input_row_bg
                row.styles.border_top = ("round", chrome.input_row_border_color)
                for ta in row.query("TextArea"):
                    ta.styles.background = chrome.textarea_bg
                    ta.styles.color = chrome.textarea_color
                for p in row.query("#oc_prompt, #claude_prompt"):
                    p.styles.color = chrome.input_prompt_color
                    p.styles.background = chrome.input_row_bg
            except Exception:
                pass

        try:
            cc = self.query_one("#chat_container", Horizontal)
            for ml in cc.query(MessageList):
                ml.styles.background = chrome.message_list_bg
                # Welcome panel sets its own Rich colors; avoid overriding Static.color.
                for w in ml.query(".new-output-hint"):
                    w.styles.background = chrome.new_output_hint_bg
                    w.styles.color = chrome.new_output_hint_color
                    w.styles.border = ("round", chrome.new_output_hint_border_color)
                # ScrollBar reads colors from scrollable parent styles
                if chrome.scrollbar_thumb_color:
                    ml.styles.scrollbar_color = chrome.scrollbar_thumb_color
                    ml.styles.scrollbar_color_hover = chrome.scrollbar_thumb_color
                    ml.styles.scrollbar_color_active = chrome.scrollbar_thumb_color
                    track = chrome.scrollbar_track_color or chrome.message_list_bg
                    ml.styles.scrollbar_background = track
                    ml.styles.scrollbar_background_hover = track
                    ml.styles.scrollbar_background_active = track
                else:
                    for key in (
                        "scrollbar_color",
                        "scrollbar_color_hover",
                        "scrollbar_color_active",
                        "scrollbar_background",
                        "scrollbar_background_hover",
                        "scrollbar_background_active",
                    ):
                        ml.styles.clear_rule(key)
        except Exception:
            pass

        try:
            cc = self.query_one("#chat_container", Horizontal)
            for node in cc.query(".message.user"):
                node.styles.color = chrome.message_user_color
            for node in cc.query(".message.assistant"):
                node.styles.color = chrome.message_assistant_color
            for node in cc.query(".message.system"):
                node.styles.color = chrome.message_system_color
            for node in cc.query(".message.tool"):
                node.styles.color = chrome.message_tool_color
            for node in cc.query(".message.error"):
                node.styles.color = chrome.message_error_color
            for node in cc.query(".message.thinking"):
                node.styles.color = chrome.message_thinking_color
            for node in cc.query(".input_help"):
                node.styles.color = chrome.input_help_color
            for b in cc.query("Button"):
                b.styles.background = chrome.button_bg
                b.styles.color = chrome.button_color
                b.styles.border = ("round", chrome.button_border_color)
        except Exception:
            pass

        # --- #main_container background ---
        try:
            mc = self.app.query_one("#main_container")
            mc.styles.background = chrome.message_list_bg
        except Exception:
            pass

        # Only trigger a full MessageList layout pass when the chrome mode actually
        # changes.  Duplicate calls (e.g. on_mount → _initialize with same mode) skip
        # this expensive step, eliminating one source of first-frame flicker.
        if mode != self._last_chrome_mode:
            self._last_chrome_mode = mode
            refresh_message_lists_on_screen(self)

    def _apply_display_mode(self, mode: str) -> None:
        mode = (mode or "opencode").lower()
        valid_modes = ("classic", "opencode", "clawcode", "claude", "minimal", "zen")
        if mode not in valid_modes:
            mode = "opencode"
        self._display_mode = mode
        try:
            container = self.query_one("#chat_container", Horizontal)
            for m in (
                "mode-classic",
                "mode-opencode",
                "mode-clawcode",
                "mode-claude",
                "mode-minimal",
                "mode-zen",
            ):
                container.remove_class(m)
            container.add_class(f"mode-{mode}")
        except Exception:
            pass

        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            right_panel = self.query_one("#right_panel_container", Vertical)
            grip = self.query_one("#right_panel_grip", RightPanelGrip)
            top = self.query_one("#chat_status_bar", Static)
            bottom = self.query_one("#bottom_status_bar", HudBar)
            classic_in = self.query_one("#message_input_widget", MessageInput)
            oc_in = self.query_one("#opencode_input", OpenCodeInput)
            claude_in = self.query_one("#claude_input", ClaudeCodeInput)

            if mode == "classic":
                sidebar.display = True
                right_panel.display = False
                grip.display = False
                top.display = True
                bottom.display = False
                classic_in.display = True
                oc_in.display = False
                claude_in.display = False
            elif mode in ("opencode", "clawcode"):
                sidebar.display = False
                right_panel.display = True
                grip.display = True
                top.display = False
                bottom.display = True
                classic_in.display = False
                oc_in.display = True
                claude_in.display = False
            elif mode == "claude":
                sidebar.display = False
                right_panel.display = False
                grip.display = False
                top.display = False
                bottom.display = True
                classic_in.display = False
                oc_in.display = False
                claude_in.display = True
            elif mode == "minimal":
                sidebar.display = False
                right_panel.display = False
                grip.display = False
                top.display = False
                bottom.display = True
                classic_in.display = False
                oc_in.display = True
                claude_in.display = False
            else:  # zen
                sidebar.display = False
                right_panel.display = False
                grip.display = False
                top.display = False
                bottom.display = False
                classic_in.display = False
                oc_in.display = True
                claude_in.display = False
        except Exception:
            pass

        self._apply_display_mode_chrome(mode)

    async def _update_info_panel(self) -> None:
        """Refresh right-side info panel (default mode)."""
        try:
            panel = self.query_one("#info_panel", InfoPanel)
        except Exception:
            return

        # Version
        app_version = self._ui_display_version()

        # cwd
        cwd = getattr(self.settings, "working_directory", "") or ""
        if len(cwd) > 60:
            cwd = "..." + cwd[-59:]

        # Session title
        session_title = self._current_session_title or self.current_session_id or "New session"

        # LSP config lines from settings
        lsp_items: list[tuple[str, str]] = []
        try:
            for name, cfg in (getattr(self.settings, "lsp", {}) or {}).items():
                cmd = getattr(cfg, "command", "") or ""
                args = getattr(cfg, "args", None) or []
                cmd_full = " ".join([cmd, *[str(a) for a in args]]).strip()
                lsp_items.append((name, cmd_full))
        except Exception:
            lsp_items = []
        lsp_lines = format_lsp_lines(sorted(lsp_items, key=lambda x: (x[0] or "").lower()))

        # Modified files (best-effort from FileTracker)
        modified: list[str] = []
        try:
            from ..file_tracker import FileTracker

            tracker = FileTracker(working_dir=getattr(self.settings, "working_directory", "") or "")
            if self.current_session_id:
                files = await tracker.list_modified_files(self.current_session_id)
                for f in files[:20]:
                    if f.additions or f.removals:
                        modified.append(f"{f.path}  +{f.additions} -{f.removals}")
                    else:
                        modified.append(f.path)
        except Exception:
            modified = []

        from ..styles.display_mode_styles import resolve_chat, resolve_chrome
        chat_s = resolve_chat(self._display_mode)
        chrome_s = resolve_chrome(self._display_mode)
        panel.set_model(
            InfoPanelModel(
                version=app_version,
                cwd=cwd,
                session_title=session_title,
                lsp_lines=lsp_lines,
                modified_files=modified,
            ),
            accent=chat_s.accent,
            muted=chrome_s.info_panel_color,
        )

    # ------------------------------------------------------------------
    # Code Awareness panel helpers
    # ------------------------------------------------------------------

    _CODE_AWARENESS_FILE_TOOLS = frozenset({
        "write", "edit", "patch", "MultiEdit",
        "Write", "Edit", "Patch", "WriteTool", "EditTool", "PatchTool",
    })
    _CODE_AWARENESS_READ_TOOLS = frozenset({
        "view", "View", "Read", "read",
    })

    def _init_input_history(self) -> None:
        """Create persistent input history store and bind it to the input widget."""
        hist_cfg = getattr(getattr(self.settings, "tui", None), "input_history", None)
        if hist_cfg is not None and not hist_cfg.enabled:
            return
        wd = getattr(self.settings, "working_directory", "") or ""
        if not wd:
            return
        try:
            granularity = getattr(hist_cfg, "granularity", "project") if hist_cfg else "project"
            retention = getattr(hist_cfg, "retention_days", 7.0) if hist_cfg else 7.0
            max_entries = getattr(hist_cfg, "max_entries", 500) if hist_cfg else 500
            store = InputHistoryStore(
                working_directory=wd,
                granularity=granularity,
                retention_days=retention,
                max_entries=max_entries,
            )
            store.load()
            store.prune_expired()
            self._input_history_store = store

            input_widget = self.query_one("#message_input_widget", MessageInput)
            input_widget.bind_persistent_history(
                store,
                session_id=self.current_session_id or "",
            )
        except Exception:
            pass

    async def _init_code_awareness(self) -> None:
        """Scan the project directory and initialise the Code Awareness panel."""
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
        except Exception:
            return
        wd = getattr(self.settings, "working_directory", "") or ""
        if not wd:
            return
        try:
            import asyncio

            from ..code_awareness.scanner import scan_project
            tree = await asyncio.get_event_loop().run_in_executor(
                None, lambda: scan_project(wd, 4)
            )
            cap.update_tree(tree)
            await self._start_code_awareness_monitor()
        except Exception:
            pass

    async def _start_code_awareness_monitor(self) -> None:
        """Start non-blocking architecture monitor when panel is available."""
        wd = getattr(self.settings, "working_directory", "") or ""
        if not wd:
            return
        if self._code_awareness_monitor is not None:
            return
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
        except Exception:
            return

        def _on_mapping(mapping, tree) -> None:
            try:
                cap.update_architecture_map(mapping, tree=tree)
            except Exception:
                pass

        def _on_file_event(event) -> None:
            try:
                cap.add_file_event(event)
            except Exception:
                pass

        lsp_mgr = getattr(self._app_context, "lsp_manager", None) if self._app_context else None

        try:
            monitor = ArchitectureAwarenessMonitor(
                working_directory=wd,
                settings=self.settings,
                on_mapping=_on_mapping,
                on_file_event=_on_file_event,
                lsp_manager=lsp_mgr,
            )
            self._code_awareness_monitor = monitor
            if monitor.current_map is not None:
                cap.update_architecture_map(monitor.current_map)
            monitor.start()
        except Exception:
            self._code_awareness_monitor = None

    def _code_awareness_mark(self, file_path: str) -> None:
        """Mark a file as modified in the Code Awareness panel."""
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
        except Exception:
            return
        try:
            rel = self._code_awareness_rel_path(file_path)
            cap.mark_file_modified(rel)
            monitor = self._code_awareness_monitor
            if monitor is not None:
                monitor.notify_file_modified(file_path)
        except Exception:
            pass

    def _code_awareness_mark_read(self, file_path: str) -> None:
        """Mark a file as read in the Code Awareness panel."""
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
        except Exception:
            return
        try:
            rel = self._code_awareness_rel_path(file_path)
            cap.mark_file_read(rel)
        except Exception:
            pass

    def _code_awareness_rel_path(self, file_path: str) -> str:
        """Normalize file path to working-directory relative path."""
        wd = getattr(self.settings, "working_directory", "") or ""
        from pathlib import Path
        fp = Path(file_path).resolve()
        if wd:
            wp = Path(wd).resolve()
            if str(fp).startswith(str(wp)):
                return str(fp)[len(str(wp)):].lstrip("\\/").replace("\\", "/")
        return file_path.replace("\\", "/")

    def _code_awareness_rescan_if_needed(self, file_path: str) -> None:
        """Rescan the project tree if a new directory appeared."""
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
        except Exception:
            return
        if cap._state.tree is None:
            return
        from pathlib import Path
        try:
            wd = getattr(self.settings, "working_directory", "") or ""
            if not wd:
                return
            fp = Path(file_path).resolve()
            parent = fp.parent
            wp = Path(wd).resolve()
            if not str(parent).startswith(str(wp)):
                return
            rel_parent = str(parent)[len(str(wp)):].lstrip("\\/").replace("\\", "/")
            from ..code_awareness.scanner import collect_all_paths
            known = collect_all_paths(cap._state.tree)
            if rel_parent and rel_parent not in known:
                import asyncio
                asyncio.create_task(self._init_code_awareness())
            monitor = self._code_awareness_monitor
            if monitor is not None:
                monitor.notify_file_modified(file_path)
        except Exception:
            pass

    def on_model_changed(self, provider: str, model: str) -> None:
        """Apply runtime model switch: rebuild LLM client from ``settings`` (updated by the app)."""

        async def _apply() -> None:
            try:
                await self._rebuild_llm_stack()
                self._update_status_bars()
                await self._update_info_panel()
            except Exception as e:
                try:
                    self.app.notify(f"Model switch failed: {e}", severity="error", timeout=6)
                except Exception:
                    pass

        asyncio.create_task(_apply())

    def _render_history_messages(self, messages, message_list: MessageList) -> None:
        """Replay persisted messages so the UI mirrors real-time 1:1.

        Reconstructs the same widget sequence that the streaming path
        (``_handle_agent_event``) produces:

        - **USER**: text + attachment file names
        - **ASSISTANT**: Reasoning block, main reply (Markdown),
          tool_use indicators, media/attachment placeholders
        - **TOOL**: tool_result entries
        """
        from ...message.service import MessageRole

        for msg in messages:
            role = msg.role

            if role == MessageRole.USER:
                text = msg.content or ""
                att_names: list[str] = []
                try:
                    for f in msg.files():
                        att_names.append(
                            getattr(f, "name", "") or getattr(f, "path", "") or "file"
                        )
                    for img in msg.images():
                        att_names.append(getattr(img, "name", "") or "image")
                except Exception:
                    att_names = []
                message_list.add_user_message(text, att_names or None)

            elif role == MessageRole.ASSISTANT:
                thinking = msg.thinking or ""
                if thinking:
                    message_list.update_thinking(thinking)

                text = msg.content or ""
                has_content = bool(text or msg.tool_calls())
                if has_content:
                    message_list.start_assistant_message()
                    if text:
                        message_list.update_content(text)
                    for tc in msg.tool_calls():
                        tool_name = getattr(tc, "name", "") or "tool"
                        tool_input = getattr(tc, "input", {}) or {}
                        message_list.add_tool_call(tool_name, tool_input)

                # finalize_message handles thinking + assistant + media placeholders
                message_list.finalize_message(msg)

            elif role == MessageRole.TOOL:
                raw = msg.content or ""
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    message_list.add_tool_result("tool", raw, False)
                    continue

                if isinstance(data, list):
                    for entry in data:
                        if not isinstance(entry, dict):
                            continue
                        tool_name = str(entry.get("tool_call_id") or "tool")
                        content = str(entry.get("content") or "")
                        is_error = bool(entry.get("is_error"))
                        message_list.add_tool_result(tool_name, content, is_error)
                elif isinstance(data, dict):
                    tool_name = str(data.get("tool_call_id") or "tool")
                    content = str(data.get("content") or "")
                    is_error = bool(data.get("is_error"))
                    message_list.add_tool_result(tool_name, content, is_error)

    async def _fire_plan_hook(self, event_name: str, context: dict[str, Any]) -> None:
        pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None
        if not pm or not getattr(pm, "hook_engine", None):
            return
        try:
            from ...llm.providers import create_provider, resolve_provider_from_model
            from ...plugin.types import HookEvent

            hook_event = getattr(HookEvent, event_name, None)
            if hook_event is None:
                return
            agent_config = self.settings.get_agent_config("coder")
            provider_name, provider_key = resolve_provider_from_model(
                agent_config.model,
                self.settings,
                agent_config,
            )
            provider_cfg = self.settings.providers.get(provider_key)
            api_key = getattr(provider_cfg, "api_key", None) if provider_cfg else None
            base_url = getattr(provider_cfg, "base_url", None) if provider_cfg else None
            provider = create_provider(
                provider_name=provider_name,
                model_id=agent_config.model,
                api_key=api_key,
                base_url=base_url,
            )
            await pm.hook_engine.fire(
                hook_event,
                context=context,
                provider=provider,
                working_directory=self.settings.working_directory,
                suppress_agent_hooks=True,
            )
        except Exception:
            return

    def _render_plan_reply(self, text: str) -> None:
        if not self.current_session_id:
            return
        message_list = self._ensure_message_list(self.current_session_id)
        message_list.display = True
        message_list.add_user_message("/plan")
        message_list.start_assistant_message()
        message_list.update_content(text)
        message_list.finalize_message()

    def _handle_plan_slash(self, raw_content: str) -> bool:
        if not self.current_session_id:
            return False
        head = raw_content.strip()
        if not head.startswith("/plan"):
            return False
        plan_state = self._get_plan_state(self.current_session_id, create=True)
        if plan_state is None:
            return False
        parts = head.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) >= 2 else ""

        if sub in {"", "on"}:
            if getattr(self, "_claw_mode_enabled", False):
                self._render_plan_reply(
                    "Disable Claw agent mode first (run /claw off) before enabling plan mode."
                )
                return True
            plan_state.mode = "plan_pending"
            asyncio.create_task(self._fire_plan_hook("PlanStart", {"session_id": self.current_session_id}))
            self._render_plan_reply("Plan mode is ON. Next prompt will generate a read-only implementation plan.")
            return True
        if sub == "off":
            plan_state.mode = "normal"
            self._render_plan_reply("Plan mode is OFF.")
            return True
        if sub == "show":
            if plan_state.last_plan_path and self._plan_store:
                body = self._plan_store.load_markdown(plan_state.last_plan_path)
                if body.strip():
                    bundle = self._plan_store.load_plan_bundle(plan_state.last_plan_path)
                    if bundle is not None:
                        plan_state.bundle = bundle
                        self._sync_hud_todos_from_plan(plan_state)
                        self._refresh_plan_panel(self.current_session_id)
                    self._render_plan_reply(body)
                    return True
            self._render_plan_reply("No saved plan artifact for this session.")
            return True
        if sub == "reject":
            plan_state.mode = "normal"
            plan_state.last_plan_path = None
            plan_state.last_plan_text = ""
            plan_state.last_user_request = ""
            plan_state.bundle = None
            self._refresh_plan_panel(self.current_session_id)
            self._render_plan_reply("Plan rejected. You can run /plan again with a new request.")
            return True
        if sub == "approve":
            if not plan_state.last_plan_text.strip():
                self._render_plan_reply("No plan is ready. Run /plan first.")
                return True
            plan_state.mode = "executing_from_plan"
            self._refresh_plan_panel(self.current_session_id)
            asyncio.create_task(
                self._fire_plan_hook(
                    "PlanApproved",
                    {
                        "session_id": self.current_session_id,
                        "plan_path": plan_state.last_plan_path,
                    },
                )
            )
            self._render_plan_reply("Plan approved. Send your next instruction to execute against the approved plan context.")
            return True
        self._render_plan_reply("Usage: /plan [on|off|show|approve|reject]")
        return True

    def _render_claw_reply(self, text: str) -> None:
        if not self.current_session_id:
            return
        message_list = self._ensure_message_list(self.current_session_id)
        message_list.display = True
        message_list.add_user_message("/claw")
        message_list.start_assistant_message()
        message_list.update_content(text)
        message_list.finalize_message()

    def _handle_claw_slash(self, raw_content: str) -> bool:
        """Handle ``/claw [on|off|status]``. Returns True if consumed."""
        if not self.current_session_id:
            return False
        head = raw_content.strip()
        if not head.startswith("/claw"):
            return False
        # Do not consume /clawteam, /clawcode, etc. (only `/claw` or `/claw <sub>`).
        if head != "/claw" and not head.startswith("/claw "):
            return False
        parts = head.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) >= 2 else ""

        if sub in {"", "on"}:
            plan_state = self._get_plan_state(self.current_session_id, create=False)
            if plan_state and plan_state.mode in ("plan_pending", "arc_plan_pending"):
                self._render_claw_reply(
                    "Disable /plan first (run /plan off) before enabling Claw agent mode (/claw)."
                )
                return True
            self._claw_mode_enabled = True
            self._render_claw_reply(
                "Claw agent mode (Claw branch) is ON. Next messages use "
                "ClawAgent.run_claw_turn until you send /claw off. "
                "Path A (Anthropic API) is /claude; path B (CLI) is /claude-cli ????see CLAW_SUPPORT_MAP."
            )
            if getattr(self.settings.desktop, "tools_require_claw_mode", False):
                asyncio.create_task(self._rebuild_llm_stack())
            return True
        if sub == "off":
            self._claw_mode_enabled = False
            self._render_claw_reply(
                "Claw agent mode (Claw branch) is OFF. Messages use the default coder agent path."
            )
            if getattr(self.settings.desktop, "tools_require_claw_mode", False):
                asyncio.create_task(self._rebuild_llm_stack())
            return True
        if sub == "status":
            st = "on" if getattr(self, "_claw_mode_enabled", False) else "off"
            self._render_claw_reply(
                f"Claw agent mode (Claw branch): {st}. "
                "Path A: /claude ? Path B: /claude-cli."
            )
            return True
        self._render_claw_reply("Usage: /claw [on|off|status]")
        return True

    def _start_agent_run(
        self,
        *,
        session_id: str,
        display_content: str,
        content_for_agent: str,
        attachments: list[FileAttachment] | None = None,
        is_plan_run: bool = False,
        plan_user_request: str = "",
        plan_artifact_scope: str = "",
        plan_routing_meta: dict[str, Any] | None = None,
        response_artifact_subdir: str = "",
        build_task_index: int = -1,
        is_claw_run: bool = False,
    ) -> None:
        run_state = self._get_run_state(session_id, create=True)
        if run_state is None or run_state.is_processing:
            return
        message_list = self._ensure_message_list(session_id)
        message_list.display = True
        # Before add_user_message ????scroll_end: suppress "New output" overlay. Previously
        # _agent_processing was set after add_user_message, so a user who had scrolled up
        # (_follow_live_tail False) hit _mark_unseen_output while still idle and got a gray
        # bar over the transcript until clicked.
        message_list._agent_processing = True
        message_list._follow_live_tail = True
        att_names = [a.name for a in attachments] if attachments else None
        message_list.add_user_message(display_content, att_names)

        run_id = uuid.uuid4().hex
        run_state.run_id = run_id
        run_state.is_processing = True
        run_state.task = None
        run_state.started_at = time.monotonic()
        run_state.spinner_frame = 0
        run_state.last_error = None
        run_state.has_unread_output = False
        run_state.is_plan_run = is_plan_run
        subdir = (response_artifact_subdir or "").strip()
        run_state.is_claw_run = is_claw_run
        run_state.response_artifact_subdir = subdir if not is_plan_run else ""
        if is_plan_run:
            run_state.plan_user_request = plan_user_request or display_content
            run_state.plan_artifact_scope = plan_artifact_scope
            run_state.plan_routing_meta = dict(plan_routing_meta or {})
        else:
            run_state.plan_user_request = plan_user_request or ""
            run_state.plan_artifact_scope = ""
            run_state.plan_routing_meta = (
                dict(plan_routing_meta or {}) if subdir else {}
            )
        run_state.build_task_index = build_task_index
        self._hud_turn_input_tokens = 0
        self._hud_turn_output_tokens = 0
        self._hud_turn_output_chars = 0
        self._start_processing_indicator()
        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.set_session_running(session_id, True)
            sidebar.set_session_unread(session_id, False)
            self._refresh_sidebar_async()
        except Exception:
            pass
        task = asyncio.create_task(
            self._process_message(session_id, run_id, content_for_agent, attachments)
        )
        run_state.task = task

    def _finalize_send_after_input(
        self,
        *,
        display_content: str,
        raw_content_for_plan: str,
        content_for_agent: str,
        attachments: list[FileAttachment],
        input_widget: MessageInput,
        skip_plan_wrap: bool = False,
        force_plan_run: bool = False,
        plan_user_request_override: str = "",
        plan_artifact_scope: str = "",
        plan_routing_meta: dict[str, Any] | None = None,
        response_artifact_subdir: str = "",
    ) -> None:
        """Archive awareness, clear input, apply /plan wrapping, start agent run."""
        plan_mode_for_run = False
        plan_state = self._get_plan_state(self.current_session_id or "", create=True)
        eff_agent = content_for_agent
        claw_run = bool(getattr(self, "_claw_mode_enabled", False))
        if claw_run:
            if plan_state and plan_state.mode in ("plan_pending", "arc_plan_pending"):
                try:
                    self.notify(
                        "Claw agent mode (/claw) conflicts with active /plan step. Run /plan off or /claw off first.",
                        timeout=4,
                    )
                except Exception:
                    pass
                return
        elif not skip_plan_wrap and plan_state:
            if plan_state.mode == "plan_pending":
                plan_mode_for_run = True
                plan_state.last_user_request = raw_content_for_plan
                eff_agent = (
                    "You are in Claude-compatible /plan mode. "
                    "Perform read-only analysis only. "
                    "Return a concrete implementation plan in markdown with sections: "
                    "Summary, Proposed changes, Risks, Test plan.\n\n"
                    f"User request:\n{raw_content_for_plan}"
                )
            elif plan_state.mode == "arc_plan_pending":
                plan_mode_for_run = True
                plan_state.last_user_request = raw_content_for_plan
                # Embed Everything Claude Code's full planner role+process+format,
                # then enforce ClawCode's stronger "planning only" contract.
                eff_agent = (
                    f"{ECC_PLANNER_MD}\n\n"
                    "Hard constraints:\n"
                    "- Do NOT write or modify any code.\n"
                    "- Do NOT propose file edits beyond describing them.\n"
                    "- Use read-only tools only. If you need info, use view/ls/glob/grep (no write tools).\n"
                    "- Stop after the plan. Code execution will happen later after the plan is approved.\n\n"
                    "Output constraints:\n"
                    "- Follow the Plan Format from the embedded planner.md.\n"
                    "- Ensure the final response includes a '## Implementation Steps' section with an ordered list of steps (each item one line).\n\n"
                    f"User request:\n{raw_content_for_plan}\n"
                )
            elif plan_state.mode == "executing_from_plan" and plan_state.last_plan_text.strip():
                eff_agent = (
                    "Execute implementation according to the approved plan below. "
                    "If the user request conflicts with plan, ask for clarification briefly.\n\n"
                    f"Approved plan:\n{plan_state.last_plan_text}\n\n"
                    f"User request:\n{raw_content_for_plan}"
                )

        if force_plan_run and not claw_run:
            plan_mode_for_run = True

        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
            cap.archive_current_turn(
                query=display_content,
                session_id=self.current_session_id,
            )
            cap.reset_current_marks()
        except Exception:
            pass

        input_widget.push_sent_history(raw_content_for_plan)
        input_widget.clear()
        try:
            input_widget.focus()
        except Exception:
            pass

        if not self.current_session_id:
            return
        self._start_agent_run(
            session_id=self.current_session_id,
            display_content=display_content,
            content_for_agent=eff_agent,
            attachments=attachments,
            is_plan_run=plan_mode_for_run,
            plan_user_request=plan_user_request_override,
            plan_artifact_scope=plan_artifact_scope,
            plan_routing_meta=plan_routing_meta,
            response_artifact_subdir=response_artifact_subdir,
            build_task_index=-1,
            is_claw_run=claw_run,
        )

    def _build_builtin_slash_context(self) -> BuiltinSlashContext:
        """Snapshot HUD/session fields for built-in slash commands (/todos, /usage, ????."""
        todos = [(t.content, str(t.status)) for t in self._hud_todos]
        agent_config = self.settings.get_agent_config("coder")
        model = agent_config.model or "Unknown"
        lower_model = (model or "").lower()
        if "gpt" in lower_model or "openai" in lower_model:
            provider_label = "openai"
        elif "gemini" in lower_model:
            provider_label = "gemini"
        else:
            provider_label = "anthropic"

        app_version = self._ui_display_version()

        cwd = str(getattr(self.settings, "working_directory", "") or "").strip() or "."
        working_dir_display = cwd if len(cwd) <= 56 else "..." + cwd[-53:]

        lsp_on = bool(
            self._app_context and getattr(self._app_context, "lsp_manager", None)
        )
        mouse_on = False
        try:
            app = getattr(self, "app", None)
            if app and hasattr(app, "is_mouse_mode_enabled"):
                mouse_on = bool(app.is_mouse_mode_enabled())
        except Exception:
            pass

        auto_compact = bool(getattr(self.settings, "auto_compact", True))
        run_state = self._get_run_state(self.current_session_id or "", create=False)
        is_agent_processing = bool(run_state and run_state.is_processing)
        display_mode = str(getattr(self, "_display_mode", "") or "")

        plan_background_tasks: list[str] = []
        if self.current_session_id:
            ps = self._get_plan_state(self.current_session_id, create=False)
            if ps and ps.bundle and ps.bundle.tasks:
                for t in ps.bundle.tasks:
                    plan_background_tasks.append(f"**{t.status}** {t.title}")

        db_total = int(self._session_prompt_tokens + self._session_completion_tokens)
        live_total = self._hud_turn_input_tokens + self._hud_turn_output_tokens
        if live_total == 0 and self._hud_turn_output_chars > 0:
            live_total = db_total + int(self._hud_turn_output_chars * 1.5)
        total_tokens = max(db_total, live_total)
        ctx_window_size = get_context_window_size(model)
        context_percent = 0
        if ctx_window_size > 0:
            context_percent = min(100, int(round((total_tokens / ctx_window_size) * 100)))
        plan_blocks_claw = False
        if self.current_session_id:
            _ps = self._get_plan_state(self.current_session_id, create=False)
            if _ps and _ps.mode in ("plan_pending", "arc_plan_pending"):
                plan_blocks_claw = True
        return BuiltinSlashContext(
            todos=todos,
            context_percent=context_percent,
            context_window_size=ctx_window_size,
            session_prompt_tokens=int(self._session_prompt_tokens),
            session_completion_tokens=int(self._session_completion_tokens),
            turn_input_tokens=int(self._hud_turn_input_tokens),
            turn_output_tokens=int(self._hud_turn_output_tokens),
            model_label=model,
            app_version=app_version,
            working_dir_display=working_dir_display,
            session_id=self.current_session_id or "",
            session_title=(self._current_session_title or ""),
            lsp_on=lsp_on,
            mouse_on=mouse_on,
            auto_compact=auto_compact,
            provider_label=provider_label,
            is_agent_processing=is_agent_processing,
            display_mode=display_mode,
            plan_background_tasks=plan_background_tasks,
            plan_blocks_claw=plan_blocks_claw,
            claw_mode_enabled=bool(getattr(self, "_claw_mode_enabled", False)),
            ui_style_mode=str(getattr(self, "_ui_style_mode", "off") or "off"),
            ui_style_selected=str(getattr(self, "_ui_style_selected", "") or ""),
            ui_style_reason=str(getattr(self, "_ui_style_reason", "") or ""),
            ui_style_top_candidates=list(getattr(self, "_ui_style_top_candidates", []) or []),
            ui_style_source=str(getattr(self, "_ui_style_source", "") or ""),
        )

    def _clawteam_loop_store(self) -> dict[str, dict[str, Any]]:
        return self._clawteam_deep_loop_state

    def _clawteam_last_response_store(self) -> dict[str, str]:
        return self._clawteam_deep_loop_last_response

    def _append_clawteam_deep_loop_log(self, session_id: str, text: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        try:
            message_list = self._ensure_message_list(sid)
            message_list.display = True
            message_list.start_assistant_message()
            message_list.update_content(text)
            message_list.finalize_message()
        except Exception:
            # Unit tests may call this helper without mounted widgets.
            return

    def _parse_clawteam_deep_loop_runtime_args(self, raw_content: str) -> tuple[bool, int]:
        """Best-effort parse for `/clawteam ... --deep_loop [--max_iters n]`."""
        head, tail = parse_slash_line(raw_content)
        ns = _parse_clawteam_namespace_slash(raw_content)
        if ns is not None:
            c_agent, c_tail = ns
            head = "clawteam"
            tail = f"--agent {c_agent}" + (f" {c_tail}" if c_tail else "")
        if head != "clawteam":
            return False, int(getattr(self.settings.closed_loop, "clawteam_deeploop_max_iters", 100) or 100)
        deep_loop = False
        max_iters = int(getattr(self.settings.closed_loop, "clawteam_deeploop_max_iters", 100) or 100)
        try:
            tokens = shlex.split((tail or "").strip())
        except Exception:
            tokens = (tail or "").split()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--deep_loop":
                deep_loop = True
                i += 1
                continue
            if tok == "--max_iters" and i + 1 < len(tokens):
                try:
                    parsed = int(tokens[i + 1])
                    if parsed >= 1:
                        max_iters = parsed
                except Exception:
                    pass
                i += 2
                continue
            i += 1
        return deep_loop, max_iters

    # Maximum chars of previous-iteration output to embed in the continuation prompt.
    # Keeps the runtime prompt bounded so it doesn't overflow the model context window.
    _DEEP_LOOP_LAST_TEXT_CAP = 4000
    # After this many consecutive iterations without a DEEP_LOOP_EVAL_JSON marker
    # from the model, the loop auto-exits to prevent a runaway 100-iteration cycle.
    _DEEP_LOOP_MAX_NO_EVAL = 3

    def _continue_clawteam_deep_loop_if_needed(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        state = self._clawteam_loop_store().get(sid)
        if not isinstance(state, dict):
            return
        run_state = self._get_run_state(sid, create=False)
        if run_state is not None and run_state.is_processing:
            return
        iter_idx = int(state.get("iter_idx", 1) or 1)
        max_iters = int(state.get("max_iters", 100) or 100)
        min_iters = int(state.get("min_iters", 2) or 2)
        last_text = self._clawteam_last_response_store().get(sid, "")
        converged, delta_score, has_eval_marker = _extract_deep_loop_eval(last_text)

        # --- Track consecutive missing DEEP_LOOP_EVAL_JSON ---
        no_eval_count = int(state.get("no_eval_count", 0) or 0)
        if has_eval_marker:
            no_eval_count = 0
        else:
            no_eval_count += 1
        state["no_eval_count"] = no_eval_count

        delta_text = f"{delta_score:.4f}" if isinstance(delta_score, float) else "unknown"
        self._append_clawteam_deep_loop_log(
            sid,
            f"[clawteam deep_loop] 迭代 {iter_idx}/{max_iters} 收敛判定："
            f" converged={str(converged).lower()} · delta_score={delta_text}"
            + (f" · no_eval={no_eval_count}" if not has_eval_marker else ""),
        )

        # Ensure the background monitor is running for this loop.
        self._start_deep_loop_monitor()

        # --- Termination checks ---
        if iter_idx >= max_iters:
            self._append_clawteam_deep_loop_log(
                sid,
                f"[clawteam deep_loop] 结束：达到最大轮次 {max_iters}/{max_iters}。",
            )
            self._clawteam_loop_store().pop(sid, None)
            self._clawteam_last_response_store().pop(sid, None)
            self._stop_deep_loop_monitor()
            return
        if converged and iter_idx >= min_iters:
            self._append_clawteam_deep_loop_log(
                sid,
                f"[clawteam deep_loop] 结束：第 {iter_idx} 轮满足收敛条件（最少轮次={min_iters}）。",
            )
            self._clawteam_loop_store().pop(sid, None)
            self._clawteam_last_response_store().pop(sid, None)
            self._stop_deep_loop_monitor()
            return
        if no_eval_count >= self._DEEP_LOOP_MAX_NO_EVAL:
            self._append_clawteam_deep_loop_log(
                sid,
                f"[clawteam deep_loop] 结束：连续 {no_eval_count} 轮未输出 DEEP_LOOP_EVAL_JSON，"
                "视为软收敛退出。请检查模型是否支持输出所需的 eval 格式。",
            )
            self._clawteam_loop_store().pop(sid, None)
            self._clawteam_last_response_store().pop(sid, None)
            self._stop_deep_loop_monitor()
            return

        # --- Prepare next iteration ---
        next_iter = iter_idx + 1
        state["iter_idx"] = next_iter
        state["last_activity_at"] = time.monotonic()  # mark activity for watchdog

        # Truncate previous output to keep the prompt within context window bounds.
        prev_output = last_text
        if len(prev_output) > self._DEEP_LOOP_LAST_TEXT_CAP:
            omitted = len(prev_output) - self._DEEP_LOOP_LAST_TEXT_CAP
            prev_output = (
                f"[...前 {omitted} 字已省略，保留最新内容...]\n"
                + prev_output[-self._DEEP_LOOP_LAST_TEXT_CAP:]
            )

        base_prompt = str(state.get("base_prompt", "") or "")
        runtime_prompt = (
            f"{base_prompt}\n\n"
            "RUNTIME ENFORCEMENT (system hard-constraint):\n"
            f"- Current iteration: {next_iter}/{max_iters}\n"
            f"- Do NOT stop before iteration {min_iters}\n"
            "- Keep using clawteam protocol and produce DEEP_LOOP_EVAL_JSON at end.\n\n"
            "Previous iteration output (for continuation):\n"
            f"{prev_output}\n"
        )
        self._start_agent_run(
            session_id=sid,
            display_content=f"[深度循环] 迭代 {next_iter}/{max_iters}",
            content_for_agent=runtime_prompt,
            attachments=None,
            is_plan_run=False,
            plan_user_request="",
            plan_artifact_scope="",
            plan_routing_meta=None,
            response_artifact_subdir="",
            build_task_index=-1,
            is_claw_run=False,
        )

    async def _run_builtin_slash_send(
        self,
        raw_content: str,
        display_content: str,
        attachments: list[FileAttachment],
        input_widget: MessageInput,
    ) -> None:
        if self._builtin_slash_inflight:
            return
        if not self._agent or not self.current_session_id:
            return
        run_state = self._get_run_state(self.current_session_id, create=True)
        if run_state is not None and run_state.is_processing:
            return

        head, tail = parse_slash_line(raw_content)
        clawteam_ns = _parse_clawteam_namespace_slash(raw_content)
        if clawteam_ns is not None:
            c_agent, c_tail = clawteam_ns
            head = "clawteam"
            tail = f"--agent {c_agent}" + (f" {c_tail}" if c_tail else "")
        if not head or head not in BUILTIN_SLASH_NAMES:
            return

        # Some built-ins may take noticeable time (DB/network/git/LLM).
        # Emit immediate acknowledgement so Ctrl+S does not look "stuck".
        pre_echoed = False
        if head in _SLOW_BUILTIN_SLASH_PRE_ECHO:
            pre_echoed = True
            try:
                input_widget.clear()
                input_widget.focus()
            except Exception:
                pass
            try:
                message_list = self._ensure_message_list(self.current_session_id)
                message_list.display = True
                att_names = [a.name for a in attachments] if attachments else None
                message_list.add_user_message(display_content, att_names)
                message_list.start_assistant_message()
                message_list.update_content(f"Running **`/{head}`** ...")
                message_list.finalize_message()
            except Exception:
                pass

        self._builtin_slash_inflight = True
        try:
            pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None
            pending_git_restore: tuple[str, list[str]] | None = None
            pending_exit_after_slash = False
            outcome = await asyncio.wait_for(
                handle_builtin_slash(
                    head,
                    tail,
                    settings=self.settings,
                    session_service=getattr(self, "_session_service", None),
                    context=self._build_builtin_slash_context(),
                    plugin_manager=pm,
                    message_service=getattr(self, "_message_service", None),
                ),
                timeout=180.0,
            )
            # Apply state patches emitted by slash handlers (non-agent side effects).
            try:
                ui_style_patch = (
                    dict(outcome.routing_meta.get("ui_style", {}))
                    if isinstance(getattr(outcome, "routing_meta", None), dict)
                    else {}
                )
            except Exception:
                ui_style_patch = {}
            if ui_style_patch:
                mode = str(ui_style_patch.get("mode", "")).strip().lower()
                if mode in ("on", "off"):
                    self._ui_style_mode = mode
                if "selected" in ui_style_patch:
                    self._ui_style_selected = str(ui_style_patch.get("selected", "")).strip()
                if "source" in ui_style_patch:
                    self._ui_style_source = str(ui_style_patch.get("source", "")).strip()
                if "reason" in ui_style_patch:
                    self._ui_style_reason = str(ui_style_patch.get("reason", "")).strip()
            if outcome.ui_action == "enable_claw_mode":
                self._claw_mode_enabled = True
                outcome.ui_action = None
                if getattr(self.settings.desktop, "tools_require_claw_mode", False):
                    asyncio.create_task(self._rebuild_llm_stack())
            if outcome.ui_action == "toggle_vim":
                if isinstance(input_widget, MessageInput):
                    outcome.assistant_text = input_widget.toggle_vim_mode()
                else:
                    outcome.assistant_text = (
                        "Vim mode toggle is only available on the standard chat input."
                    )
                outcome.ui_action = None
            if outcome.ui_action == "show_theme_selector":
                app = getattr(self, "app", None)
                fn = getattr(app, "action_show_theme_selector", None) if app else None
                if callable(fn):
                    fn()
                outcome.assistant_text = (
                    outcome.assistant_text
                    or "Theme picker opened. Shortcut: **Ctrl+Shift+T**."
                )
                outcome.ui_action = None
            if outcome.ui_action == "show_rename_dialog":
                app = getattr(self, "app", None)
                sid = (self.current_session_id or "").strip()
                title = (self._current_session_title or "").strip() or "Untitled"
                if app and sid:
                    from ..components.dialogs.rename_session import RenameSessionDialog

                    def on_renamed(result: tuple[str, str] | None) -> None:
                        if result:
                            rsid, new_title = result
                            rename_fn = getattr(app, "rename_session", None)
                            if callable(rename_fn):
                                rename_fn(rsid, new_title)

                    app.push_screen(
                        RenameSessionDialog(session_id=sid, current_title=title),
                        on_renamed,
                    )
                outcome.assistant_text = outcome.assistant_text or "Rename dialog opened."
                outcome.ui_action = None
            if outcome.ui_action == "switch_session":
                app = getattr(self, "app", None)
                fn = getattr(app, "action_switch_session", None) if app else None
                if callable(fn):
                    fn()
                outcome.assistant_text = (
                    outcome.assistant_text or "Session switcher opened (**Ctrl+A**)."
                )
                outcome.ui_action = None
            if outcome.ui_action == "reload_session_history":
                sid = self.current_session_id
                if sid:
                    await self._show_session_message_list(sid, force_reload=True)
                outcome.ui_action = None
            if outcome.ui_action == "confirm_git_restore":
                pending_git_restore = (
                    outcome.git_restore_cwd or ".",
                    list(outcome.git_restore_paths or []),
                )
                outcome.ui_action = None
            if outcome.clear_session_tool_permissions:
                app = getattr(self, "app", None)
                sid_perm = (self.current_session_id or "").strip()
                clear_fn = getattr(app, "clear_session_tool_permissions", None) if app else None
                if callable(clear_fn) and sid_perm:
                    clear_fn(sid_perm)
            mode_apply = getattr(outcome, "apply_display_mode", None)
            if mode_apply:
                mode_s = str(mode_apply).strip()
                if mode_s:
                    self.set_display_mode(mode_s)
                    save_dm = getattr(self.app, "_save_ui_preferences", None)
                    if callable(save_dm):
                        try:
                            save_dm(display_mode=mode_s)
                        except Exception:
                            pass
                    try:
                        self.app.display_mode = mode_s
                    except Exception:
                        pass
            if outcome.ui_action == "open_model_dialog":
                app = getattr(self, "app", None)
                fn = getattr(app, "action_change_model", None) if app else None
                if callable(fn):
                    fn()
                outcome.assistant_text = (
                    outcome.assistant_text or "Model picker opened. Shortcut: **Ctrl+O**."
                )
                outcome.ui_action = None
            if outcome.ui_action == "open_display_mode":
                app = getattr(self, "app", None)
                fn = getattr(app, "action_switch_display_mode", None) if app else None
                if callable(fn):
                    fn()
                outcome.assistant_text = (
                    outcome.assistant_text
                    or "Display mode picker opened. Shortcut: **Ctrl+D**."
                )
                outcome.ui_action = None
            if outcome.ui_action == "exit_app":
                pending_exit_after_slash = True
                outcome.assistant_text = outcome.assistant_text or "Opening quit confirmation..."
                outcome.ui_action = None
            if outcome.ui_action == "show_help_screen":
                self.action_show_help()
                outcome.assistant_text = (
                    outcome.assistant_text or "Help opened. Shortcut: **F1** / **Ctrl+H**."
                )
                outcome.ui_action = None
            if outcome.ui_action == "open_clawcode_config_external":
                self._open_clawcode_json_external_editor()
                outcome.assistant_text = (
                    outcome.assistant_text
                    or "If an editor opened, edit **`.clawcode.json`** and save; then restart if needed."
                )
                outcome.ui_action = None
            if outcome.kind == "assistant_message":
                if not pre_echoed:
                    input_widget.clear()
                    try:
                        input_widget.focus()
                    except Exception:
                        pass
                message_list = self._ensure_message_list(self.current_session_id)
                message_list.display = True
                if not pre_echoed:
                    att_names = [a.name for a in attachments] if attachments else None
                    message_list.add_user_message(display_content, att_names)
                message_list.start_assistant_message()
                message_list.update_content(outcome.assistant_text or "")
                message_list.finalize_message()
                clip_txt = getattr(outcome, "clipboard_text", None) or ""
                if clip_txt.strip():
                    app_clip = getattr(self, "app", None)
                    copy_fn = getattr(app_clip, "copy_to_clipboard", None) if app_clip else None
                    if callable(copy_fn):
                        copy_fn(clip_txt)
                fork_switch = (getattr(outcome, "switch_to_session_id", None) or "").strip()
                if fork_switch:
                    await self.switch_session(fork_switch)
                if pending_exit_after_slash:
                    app_q = getattr(self, "app", None)
                    quit_fn = getattr(app_q, "action_quit", None) if app_q else None
                    if callable(quit_fn):
                        quit_fn()
                if pending_git_restore:
                    cwd_s, paths = pending_git_restore
                    app = getattr(self, "app", None)
                    if app and paths:

                        def _on_git_restore(confirmed: bool) -> None:
                            if not confirmed:
                                return

                            async def _do_restore() -> None:
                                from pathlib import Path

                                ok, err = await asyncio.to_thread(
                                    git_restore_tracked_paths_to_head,
                                    Path(cwd_s),
                                    paths,
                                )
                                notify = getattr(app, "notify", None)
                                if callable(notify):
                                    if ok:
                                        notify(
                                            f"Restored {len(paths)} path(s) to HEAD.",
                                            severity="information",
                                            timeout=5,
                                        )
                                    else:
                                        notify(
                                            f"Git restore failed: {err}",
                                            severity="error",
                                            timeout=8,
                                        )

                            asyncio.create_task(_do_restore())

                        app.push_screen(GitRestoreDialog(paths), _on_git_restore)
                return

            if outcome.kind == "agent_prompt" and outcome.agent_user_text:
                deeploop_meta = getattr(outcome, "clawteam_deeploop_meta", None)
                sid_slash = (self.current_session_id or "").strip()
                if sid_slash and isinstance(deeploop_meta, dict) and deeploop_meta:
                    clawteam_deeploop_set_pending(sid_slash, deeploop_meta)
                if head == "clawteam" and sid_slash:
                    deep_loop_enabled, deep_loop_max_iters = self._parse_clawteam_deep_loop_runtime_args(raw_content)
                    if deep_loop_enabled:
                        self._clawteam_loop_store()[sid_slash] = {
                            "iter_idx": 1,
                            "max_iters": deep_loop_max_iters,
                            "min_iters": 2,
                            "base_prompt": outcome.agent_user_text,
                            "requirement": tail,
                            "no_eval_count": 0,
                            "last_activity_at": time.monotonic(),
                            "stall_count": 0,
                        }
                        self._clawteam_last_response_store().pop(sid_slash, None)
                        self._start_deep_loop_monitor()
                    else:
                        self._clawteam_loop_store().pop(sid_slash, None)
                        self._clawteam_last_response_store().pop(sid_slash, None)
                is_multi_plan = head == "multi-plan"
                is_multi_execute = head == "multi-execute"
                is_multi_backend = head == "multi-backend"
                is_multi_frontend = head == "multi-frontend"
                is_multi_workflow = head == "multi-workflow"
                is_orchestrate = head == "orchestrate"
                artifact_scope = "multi-plan" if is_multi_plan else ("multi-execute" if is_multi_execute else "")
                response_subdir = ""
                if is_multi_backend:
                    response_subdir = "multi-backend"
                elif is_multi_frontend:
                    response_subdir = "multi-frontend"
                elif is_multi_workflow:
                    response_subdir = "multi-workflow"
                elif is_orchestrate:
                    response_subdir = "orchestrate"
                self._finalize_send_after_input(
                    display_content=display_content,
                    raw_content_for_plan=raw_content,
                    content_for_agent=outcome.agent_user_text,
                    attachments=attachments,
                    input_widget=input_widget,
                    skip_plan_wrap=True,
                    force_plan_run=(is_multi_plan or is_multi_execute),
                    plan_user_request_override=tail
                    if (
                        is_multi_plan
                        or is_multi_execute
                        or is_multi_backend
                        or is_multi_frontend
                        or is_multi_workflow
                        or is_orchestrate
                    )
                    else "",
                    plan_artifact_scope=artifact_scope,
                    plan_routing_meta=(
                        outcome.routing_meta
                        if (
                            is_multi_plan
                            or is_multi_execute
                            or is_multi_backend
                            or is_multi_frontend
                            or is_multi_workflow
                            or is_orchestrate
                        )
                        else None
                    ),
                    response_artifact_subdir=response_subdir,
                )
        except TimeoutError:
            message_list = self._ensure_message_list(self.current_session_id)
            message_list.display = True
            if not pre_echoed:
                att_names = [a.name for a in attachments] if attachments else None
                message_list.add_user_message(display_content, att_names)
            message_list.start_assistant_message()
            message_list.update_content(
                f"**`/{head}`** is taking longer than expected. Please retry, or run **`/clear`** to reset current session context."
            )
            message_list.finalize_message()
        except Exception as e:
            message_list = self._ensure_message_list(self.current_session_id)
            message_list.display = True
            if not pre_echoed:
                att_names = [a.name for a in attachments] if attachments else None
                message_list.add_user_message(display_content, att_names)
            message_list.start_assistant_message()
            message_list.update_content(f"**`/{head}` failed:** {e}")
            message_list.finalize_message()
        finally:
            self._builtin_slash_inflight = False

    def _start_plan_build(self, session_id: str) -> None:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state:
            return
        if plan_state.bundle is None and plan_state.last_plan_path and self._plan_store:
            plan_state.bundle = self._plan_store.load_plan_bundle(plan_state.last_plan_path)
        if not plan_state.bundle:
            return
        run_state = self._get_run_state(session_id, create=False)
        if run_state and run_state.is_processing:
            return
        bundle = plan_state.bundle
        if not bundle.tasks:
            return
        bundle.execution.interrupted = False
        bundle.execution.last_error = ""
        bundle.execution.is_building = True
        bundle.execution.current_task_index = -1
        bundle.execution.started_at = int(time.time())
        bundle.execution.finished_at = 0
        bundle.execution.last_progress_at = int(time.time())
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        self._sync_hud_todos_from_plan(plan_state)
        self._refresh_plan_panel(session_id)
        self._run_next_plan_task(session_id)

    def _resume_plan_build(self, session_id: str) -> None:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return
        run_state = self._get_run_state(session_id, create=False)
        if run_state and run_state.is_processing:
            return
        bundle = plan_state.bundle
        if not bundle.tasks:
            return
        if all(t.status == "completed" for t in bundle.tasks):
            self._reconcile_plan_bundle_execution(session_id, bundle)
            self._refresh_plan_panel(session_id)
            return
        bundle.execution.is_building = True
        bundle.execution.interrupted = False
        bundle.execution.last_progress_at = int(time.time())
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        self._refresh_plan_panel(session_id)
        self._run_next_plan_task(session_id)

    def _retry_current_plan_task(self, session_id: str) -> None:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return
        run_state = self._get_run_state(session_id, create=False)
        if run_state and run_state.is_processing:
            return
        bundle = plan_state.bundle
        idx = int(bundle.execution.current_task_index)
        if not (0 <= idx < len(bundle.tasks)):
            return
        task_item = bundle.tasks[idx]
        task_item.status = "pending"
        task_item.result_summary = ""
        bundle.execution.is_building = True
        bundle.execution.interrupted = False
        bundle.execution.last_error = ""
        bundle.execution.last_progress_at = int(time.time())
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        self._refresh_plan_panel(session_id)
        self._run_next_plan_task(session_id)

    def _stop_plan_build(self, session_id: str) -> None:
        self._abort_active_build_run(
            session_id,
            reason="Build interrupted by user.",
            mark_failed=False,
            interrupted=True,
            allow_auto_retry=False,
        )

    def _run_next_plan_task(self, session_id: str) -> None:
        plan_state = self._get_plan_state(session_id, create=False)
        if not plan_state or not plan_state.bundle:
            return
        bundle = plan_state.bundle
        if not bundle.execution.is_building:
            return
        next_index = -1
        for i, t in enumerate(bundle.tasks):
            if t.status in ("pending", "failed"):
                next_index = i
                break
        if next_index == -1:
            bundle.execution.is_building = False
            bundle.execution.current_task_index = -1
            bundle.execution.finished_at = int(time.time())
            bundle.execution.interrupted = False
            bundle.execution.last_error = ""
            plan_state.mode = "normal"
            if self._plan_store:
                self._plan_store.save_plan_bundle(bundle)
            self._sync_hud_todos_from_plan(plan_state)
            self._refresh_plan_panel(session_id)
            try:
                message_list = self._ensure_message_list(session_id)
                plan_title = self._extract_plan_title(bundle.plan_text, bundle.user_request)
                message_list.start_assistant_message()
                message_list.update_content(f"{plan_title} [Build Completed]")
                message_list.finalize_message()
            except Exception:
                pass
            return

        task_item = bundle.tasks[next_index]
        task_item.status = "in_progress"
        bundle.execution.current_task_index = next_index
        bundle.execution.last_progress_at = int(time.time())
        bundle.execution.stall_count = 0
        if self._plan_store:
            self._plan_store.save_plan_bundle(bundle)
        self._sync_hud_todos_from_plan(plan_state)
        self._refresh_plan_panel(session_id)
        prompt = compose_task_execution_prompt(bundle.plan_text, task_item)
        if bundle.execution.last_error:
            prompt = (
                f"{prompt}\n\nPrevious attempt failure:\n{bundle.execution.last_error}\n"
                "Focus on fixing this failure and continue."
            )
        self._start_agent_run(
            session_id=session_id,
            display_content=f"[Build] {task_item.title}",
            content_for_agent=prompt,
            attachments=None,
            is_plan_run=False,
            build_task_index=next_index,
        )

    def action_send_message(self) -> None:
        """Send the current message (bound to Ctrl+S)."""
        try:
            input_widget = self._get_active_input()
        except Exception:
            input_widget = self.query_one("#message_input_widget", MessageInput)
        raw_content = input_widget.text.strip()
        attachments = list(input_widget.attachments)  # snapshot before clear

        if not raw_content and not attachments:
            return

        if not self._agent or not self.current_session_id:
            return

        run_state = self._get_run_state(self.current_session_id, create=True)
        if run_state is not None and run_state.is_processing:
            try:
                self.notify(
                    "Agent busy (model or tools running). Wait for this turn to finish.",
                    timeout=2,
                )
            except Exception:
                pass
            return

        display_content = raw_content
        content_for_agent = raw_content
        pm = getattr(self._app_context, "plugin_manager", None) if self._app_context else None
        if raw_content.startswith("/"):
            if self._handle_claw_slash(raw_content):
                input_widget.clear()
                try:
                    input_widget.focus()
                except Exception:
                    pass
                return
            if self._handle_plan_slash(raw_content):
                input_widget.clear()
                try:
                    input_widget.focus()
                except Exception:
                    pass
                return
            head, tail = parse_slash_line(raw_content)
            clawteam_ns = _parse_clawteam_namespace_slash(raw_content)
            if clawteam_ns is not None:
                c_agent, c_tail = clawteam_ns
                head = "clawteam"
                tail = f"--agent {c_agent}" + (f" {c_tail}" if c_tail else "")
            if head == "arc-plan":
                # Single-shot alternative to `/plan`: generate a plan immediately from `/arc-plan <request>`.
                plan_state = self._get_plan_state(self.current_session_id, create=True)
                request = (tail or "").strip()
                if not request:
                    input_widget.clear()
                    try:
                        input_widget.focus()
                    except Exception:
                        pass
                    message_list = self._ensure_message_list(self.current_session_id)
                    message_list.display = True
                    message_list.add_user_message("/arc-plan")
                    message_list.start_assistant_message()
                    message_list.update_content("Usage: /arc-plan <request>")
                    message_list.finalize_message()
                    return

                plan_state.mode = "arc_plan_pending"
                plan_state.last_plan_path = None
                plan_state.last_plan_text = ""
                plan_state.last_user_request = ""
                plan_state.bundle = None
                asyncio.create_task(
                    self._fire_plan_hook("PlanStart", {"session_id": self.current_session_id})
                )

                # Start an agent run right away; _finalize_send_after_input will wrap with arc-plan prompt.
                self._finalize_send_after_input(
                    display_content=request,
                    raw_content_for_plan=request,
                    content_for_agent=request,
                    attachments=attachments,
                    input_widget=input_widget,
                    skip_plan_wrap=False,
                )
                return
            plugin_ns = _parse_plugin_namespace_slash(raw_content)
            if plugin_ns is not None:
                from ...plugin.slash import dispatch_slash

                plugin_cmd, plugin_tail = plugin_ns
                rewritten = f"/{plugin_cmd}" + (f" {plugin_tail}" if plugin_tail else "")
                slash = dispatch_slash(rewritten, self.settings, pm)
                if slash is not None:
                    if slash.consume_without_llm:
                        input_widget.clear()
                        try:
                            input_widget.focus()
                        except Exception:
                            pass
                        message_list = self._ensure_message_list(self.current_session_id)
                        message_list.display = True
                        att_names = [a.name for a in attachments] if attachments else None
                        message_list.add_user_message(display_content, att_names)
                        message_list.start_assistant_message()
                        message_list.update_content(slash.plugin_reply or "")
                        message_list.finalize_message()
                        if _plugin_slash_reply_ok_for_skill_refresh(slash.plugin_reply):
                            self._refresh_slash_skill_autocomplete()
                        return
                    content_for_agent = slash.llm_user_text
                    self._finalize_send_after_input(
                        display_content=display_content,
                        raw_content_for_plan=raw_content,
                        content_for_agent=content_for_agent,
                        attachments=attachments,
                        input_widget=input_widget,
                        skip_plan_wrap=False,
                    )
                    return
            if head in BUILTIN_SLASH_NAMES:
                raw_for_builtin = raw_content
                if clawteam_ns is not None:
                    raw_for_builtin = f"/clawteam {tail}"
                asyncio.create_task(
                    self._run_builtin_slash_send(
                        raw_for_builtin,
                        display_content,
                        attachments,
                        input_widget,
                    )
                )
                return
            from ...plugin.slash import dispatch_slash

            slash = dispatch_slash(raw_content, self.settings, pm)
            if slash is not None:
                if slash.consume_without_llm:
                    input_widget.clear()
                    try:
                        input_widget.focus()
                    except Exception:
                        pass
                    message_list = self._ensure_message_list(self.current_session_id)
                    message_list.display = True
                    att_names = [a.name for a in attachments] if attachments else None
                    message_list.add_user_message(display_content, att_names)
                    message_list.start_assistant_message()
                    message_list.update_content(slash.plugin_reply or "")
                    message_list.finalize_message()
                    if head == "plugin" and _plugin_slash_reply_ok_for_skill_refresh(
                        slash.plugin_reply
                    ):
                        self._refresh_slash_skill_autocomplete()
                    return
                content_for_agent = slash.llm_user_text

        # UI style gating and prompt prefixing for normal user messages.
        if not raw_content.startswith("/") and is_ui_intent(content_for_agent):
            _ui_host = str(getattr(self.settings, "cli_launch_directory", "") or "").strip() or None
            wd_ui = self.settings.working_directory or "."
            styles = load_ui_catalog(wd_ui, cli_launch_directory=_ui_host)
            selected_slug = (self._ui_style_selected or "").strip()
            if self._ui_style_mode == "on" and not selected_slug:
                scene_tags: list[str] = derive_scene_tags(content_for_agent)
                scene_tags.extend(load_agent_scene_tags(wd_ui, cli_launch_directory=_ui_host))
                dm = str(self._display_mode or "").lower()
                if dm in ("opencode", "clawcode", "claude"):
                    scene_tags.append("component_architecture")
                pick = select_ui_style_auto(
                    content_for_agent,
                    styles,
                    scene_tags=scene_tags,
                    preferred_slug=str(getattr(self.settings, "ui_style_default_slug", "") or ""),
                )
                if pick is not None:
                    # Always adopt highest raw-score style; confidence is informational only.
                    self._ui_style_selected = pick.slug
                    self._ui_style_source = "auto"
                    n = ui_style_auto_pick_top_n()
                    detail_parts = [pick.reason, pick.rubric]
                    if pick.top_scores_preview:
                        detail_parts.append(f"Top-{n} 原始分: {pick.top_scores_preview}")
                    self._ui_style_reason = "\n\n".join(p for p in detail_parts if p)
                    self._ui_style_top_candidates = list(pick.top_candidates)
                    selected_slug = pick.slug
                    try:
                        self.notify(
                            f"UI style auto-selected: `{pick.slug}` (confidence `{pick.confidence}`). "
                            f"`/ui-style why` — 标准与 Top-{n} 分数。",
                            timeout=5,
                        )
                    except Exception:
                        pass
                elif not styles:
                    message_list = self._ensure_message_list(self.current_session_id)
                    message_list.display = True
                    att_names = [a.name for a in attachments] if attachments else None
                    message_list.add_user_message(display_content, att_names)
                    message_list.start_assistant_message()
                    hints = ui_catalog_candidate_hints(wd_ui, cli_launch_directory=_ui_host)
                    hint_lines = "\n".join(f"- `{p}`" for p in hints[:3])
                    message_list.update_content(
                        "UI style mode is **on**, but no style catalog is available.\n"
                        "Run `/ui-style off` to bypass.\n"
                        "Catalog lookup paths:\n"
                        f"{hint_lines}\n"
                        "If none exists, generate it with: `py -3 scripts/build_ui_style_catalog.py`."
                    )
                    message_list.finalize_message()
                    input_widget.clear()
                    try:
                        input_widget.focus()
                    except Exception:
                        pass
                    return
            if selected_slug and styles:
                entry = next((s for s in styles if s.slug == selected_slug), None)
                if entry is not None:
                    anti = load_ui_anti_patterns(wd_ui, slug=entry.slug, cli_launch_directory=_ui_host)
                    anti_rules = load_ui_anti_pattern_rules(
                        wd_ui, slug=entry.slug, cli_launch_directory=_ui_host
                    )
                    content_for_agent = (
                        style_prompt_prefix(entry)
                        + ui_critic_checklist(entry, anti_patterns=anti, anti_rules=anti_rules)
                        + content_for_agent
                    )

        self._finalize_send_after_input(
            display_content=display_content,
            raw_content_for_plan=raw_content,
            content_for_agent=content_for_agent,
            attachments=attachments,
            input_widget=input_widget,
            skip_plan_wrap=False,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self.current_session_id:
            return
        if event.button.id == "plan_build_button":
            self._start_plan_build(self.current_session_id)
            return
        if event.button.id == "plan_stop_button":
            self._stop_plan_build(self.current_session_id)
            return
        if event.button.id == "plan_retry_button":
            self._retry_current_plan_task(self.current_session_id)
            return
        if event.button.id == "plan_resume_button":
            self._resume_plan_build(self.current_session_id)

    async def _process_message(
        self,
        session_id: str,
        run_id: str,
        content: str,
        attachments: list[FileAttachment] | None = None,
    ) -> None:
        """Process a user message through the agent.

        Args:
            content: Message content
            attachments: Optional file attachments
        """
        try:
            run_state = self._get_run_state(session_id, create=False)
            plan_mode_for_run = bool(run_state and run_state.is_plan_run)
            is_claw_branch = bool(run_state and run_state.is_claw_run)
            if is_claw_branch:
                from ...llm.claw import ClawAgent

                if isinstance(self._agent, ClawAgent):
                    async for event in self._agent.run_claw_turn(
                        session_id,
                        content,
                        attachments=attachments,
                    ):
                        await self._handle_agent_event(session_id, run_id, event)
                        await asyncio.sleep(0)
                else:
                    async for event in self._agent.run(
                        session_id,
                        content,
                        attachments=attachments,
                        plan_mode=plan_mode_for_run,
                    ):
                        await self._handle_agent_event(session_id, run_id, event)
                        await asyncio.sleep(0)
            else:
                async for event in self._agent.run(
                    session_id,
                    content,
                    attachments=attachments,
                    plan_mode=plan_mode_for_run,
                ):
                    await self._handle_agent_event(session_id, run_id, event)
                    await asyncio.sleep(0)

        except Exception as e:
            run_state = self._get_run_state(session_id, create=False)
            if run_state is not None and run_state.run_id == run_id:
                run_state.last_error = str(e)
            if self.current_session_id == session_id:
                message_list = self._ensure_message_list(session_id)
                message_list.add_error(f"Error: {e}")
        finally:
            run_state = self._get_run_state(session_id, create=False)
            build_idx_snapshot = -1
            if run_state is not None and run_state.run_id == run_id:
                build_idx_snapshot = int(run_state.build_task_index)
                elapsed = max(0.0, time.monotonic() - float(run_state.started_at or 0.0))
                run_state.last_turn_duration_str = format_hud_session_duration(elapsed)
                run_state.is_processing = False
                run_state.task = None
                run_state.is_plan_run = False
                run_state.is_claw_run = False
                run_state.plan_user_request = ""
                run_state.build_task_index = -1
                try:
                    sidebar = self.query_one("#sidebar", Sidebar)
                    sidebar.set_session_running(session_id, False)
                    sidebar.set_session_waiting(session_id, False)
                    await sidebar.refresh_sessions()
                except Exception:
                    pass
                self._stop_processing_indicator()
                if self.current_session_id == session_id:
                    message_list = self._ensure_message_list(session_id)
                    message_list._agent_processing = False
                    message_list.force_final_refresh()
                    await asyncio.sleep(0)
            # Continue deep_loop after the run lock is released (is_processing=False).
            # The RESPONSE handler's call_later fires while is_processing is still True
            # (due to asyncio.sleep(0) yield points), so this finally-based call is the
            # reliable path — mirrors plan_task's _run_next_plan_task pattern below.
            self.call_later(lambda sid=session_id: self._continue_clawteam_deep_loop_if_needed(sid))

            if build_idx_snapshot >= 0:
                await self._recover_stale_plan_task_after_run(session_id, build_idx_snapshot)
                # After run lock is released, continue the build queue (next task or retry).
                # Scheduling here avoids a race where call_later from RESPONSE ran while
                # is_processing was still True and _start_agent_run returned without starting.
                self.call_later(lambda sid=session_id: self._run_next_plan_task(sid))

    def _maybe_finalize_clawteam_deeploop_from_assistant(
        self, session_id: str, assistant_plain: str
    ) -> None:
        if "DEEP_LOOP_WRITEBACK_JSON:" not in (assistant_plain or ""):
            return
        if not bool(getattr(self.settings.closed_loop, "clawteam_deeploop_auto_writeback_enabled", True)):
            return
        meta = clawteam_deeploop_get_pending(session_id)
        if not meta:
            return
        tecap_id = str(meta.get("tecap_id") or "").strip()
        if not tecap_id:
            return
        from ...learning.service import LearningService

        role_raw = meta.get("role_ecap_map")
        role_ecap_map: dict[str, str] = (
            {str(k): str(v) for k, v in dict(role_raw).items()} if isinstance(role_raw, dict) else {}
        )
        svc = LearningService(self.settings)
        res = svc.finalize_clawteam_deeploop_from_output(
            tecap_id=tecap_id,
            role_ecap_map=role_ecap_map,
            output_text=assistant_plain,
            trace_id=str(meta.get("trace_id") or ""),
            cycle_id=str(meta.get("cycle_id") or ""),
            policy_id=str(meta.get("policy_id") or ""),
            domain=str(meta.get("domain") or ""),
            experiment_id=str(meta.get("experiment_id") or ""),
        )
        if not res.get("skipped"):
            clawteam_deeploop_clear_pending(session_id)

    async def _handle_agent_event(self, session_id: str, run_id: str, event: AgentEvent) -> None:
        """Handle an agent event.

        Args:
            event: Agent event
        """
        from ...llm.agent import AgentEventType

        run_state = self._get_run_state(session_id, create=False)
        if run_state is not None and run_state.run_id != run_id:
            return
        if (
            run_state is not None
            and run_state.build_task_index >= 0
            and event.type
            in (
                AgentEventType.THINKING,
                AgentEventType.CONTENT_DELTA,
                AgentEventType.TOOL_USE,
                AgentEventType.TOOL_RESULT,
                AgentEventType.RESPONSE,
                AgentEventType.ERROR,
            )
        ):
            self._touch_plan_progress(session_id)

        message_list = self._ensure_message_list(session_id)
        is_visible_session = self.current_session_id == session_id
        message_list.display = is_visible_session

        def _mark_background_output() -> None:
            if not is_visible_session:
                self._mark_session_unread(session_id)
                self._refresh_sidebar_async()

        # Update deep_loop activity timestamp so the watchdog knows the loop is alive.
        _dl_state = self._clawteam_loop_store().get(session_id)
        if isinstance(_dl_state, dict):
            _dl_state["last_activity_at"] = time.monotonic()

        match event.type:
            case AgentEventType.USAGE:
                if is_visible_session and event.usage:
                    self._hud_turn_input_tokens += event.usage.input_tokens
                    self._hud_turn_output_tokens += event.usage.output_tokens
                    self._mark_hud_dirty()

            case AgentEventType.THINKING:
                message_list.update_thinking(event.content or "")
                _mark_background_output()

            case AgentEventType.CONTENT_DELTA:
                message_list.update_content(event.content or "")
                if is_visible_session and event.content:
                    prev = self._hud_turn_output_chars
                    self._hud_turn_output_chars += len(event.content)
                    if self._hud_turn_output_chars // 80 > prev // 80:
                        self._mark_hud_dirty()
                _mark_background_output()

            case AgentEventType.TOOL_USE:
                hud_only = getattr(event, "hud_only", False)
                params: Any = event.tool_input
                if not isinstance(params, dict):
                    params = {}

                def _normalize_todo_status(raw: Any) -> str | None:
                    if not isinstance(raw, str):
                        return None
                    s = raw.strip().lower()
                    if s in ("pending", "not_started"):
                        return "pending"
                    if s in ("in_progress", "running"):
                        return "in_progress"
                    if s in ("completed", "complete", "done"):
                        return "completed"
                    return None

                def _resolve_task_index(task_id: str) -> int | None:
                    mapped = self._hud_task_id_to_index.get(task_id)
                    if isinstance(mapped, int) and 0 <= mapped < len(self._hud_todos):
                        return mapped
                    if task_id.isdigit():
                        numeric_index = int(task_id) - 1
                        if 0 <= numeric_index < len(self._hud_todos):
                            return numeric_index
                    return None

                # Todos: aggregate runtime tool inputs (best-effort; only shows when tool inputs carry todos/tasks)
                if is_visible_session and event.tool_name:
                    updated = False

                    if event.tool_name == "TodoWrite" and isinstance(params.get("todos"), list):
                        todos_raw = params.get("todos")
                        new_todos: list[HudTodoItem] = []
                        for t in todos_raw:
                            if not isinstance(t, dict):
                                continue
                            content = str(t.get("content") or "").strip()
                            status_norm = _normalize_todo_status(t.get("status"))
                            if content and status_norm:
                                new_todos.append(HudTodoItem(content=content, status=status_norm))  # type: ignore[arg-type]
                        if new_todos:
                            self._hud_todos = new_todos
                            self._hud_task_id_to_index.clear()
                            updated = True

                    elif event.tool_name == "TaskCreate":
                        task_id_raw = params.get("taskId")
                        if task_id_raw is None:
                            task_id_raw = event.tool_call_id
                        task_id = str(task_id_raw).strip() if task_id_raw is not None else ""

                        content = (
                            str(params.get("subject") or params.get("description") or "").strip()
                            or "Untitled task"
                        )
                        status_norm = _normalize_todo_status(params.get("status")) or "pending"

                        self._hud_todos.append(HudTodoItem(content=content, status=status_norm))  # type: ignore[arg-type]
                        if task_id:
                            self._hud_task_id_to_index[task_id] = len(self._hud_todos) - 1
                        updated = True

                    elif event.tool_name == "TaskUpdate":
                        task_id_raw = params.get("taskId")
                        if task_id_raw is not None:
                            task_id = str(task_id_raw).strip()
                            idx = _resolve_task_index(task_id) if task_id else None
                            if idx is not None:
                                status_norm = _normalize_todo_status(params.get("status"))
                                if status_norm:
                                    self._hud_todos[idx].status = status_norm  # type: ignore[assignment]
                                content = str(
                                    params.get("subject") or params.get("description") or ""
                                ).strip()
                                if content:
                                    self._hud_todos[idx].content = content
                                updated = True

                    if updated:
                        self._mark_hud_dirty()

                if (
                    is_visible_session
                    and event.tool_call_id
                    and event.tool_name
                    and event.tool_name not in _HUD_SKIP_RUNNING_LINE_TOOLS
                ):
                    tgt = extract_tool_target_for_hud(event.tool_name, params)
                    self._hud_running_tools[event.tool_call_id] = HudRunningTool(
                        name=event.tool_name, target=tgt
                    )
                    self._mark_hud_dirty()

                if event.tool_name and not hud_only:
                    message_list.add_tool_call(
                        event.tool_name,
                        event.tool_input or {},
                        tool_call_id=event.tool_call_id,
                    )
                    _mark_background_output()

                # Code Awareness: mark file as modified for file-editing tools
                if is_visible_session and event.tool_name in self._CODE_AWARENESS_FILE_TOOLS:
                    fp = str(params.get("file_path") or params.get("path") or "").strip()
                    if fp:
                        self._code_awareness_mark(fp)
                if is_visible_session and event.tool_name in self._CODE_AWARENESS_READ_TOOLS:
                    fp = str(params.get("file_path") or params.get("path") or "").strip()
                    if fp:
                        self._code_awareness_mark_read(fp)

                # Continue, TOOL_RESULT will update agent/tool completion counters.

                if (
                    is_visible_session
                    and not hud_only
                    and event.tool_name in ("Agent", "Task", "agent")
                    and event.tool_call_id
                ):
                    subagent_type = str(
                        params.get("agent") or params.get("subagent_type") or "general-purpose"
                    )
                    task = (
                        params.get("task")
                        or params.get("prompt")
                        or params.get("context")
                        or ""
                    )
                    desc = str(task).strip() if task else "Sub-agent task"
                    m_raw = params.get("model")
                    model_val = str(m_raw).strip() if m_raw is not None else ""
                    self._hud_agent_entries[event.tool_call_id] = HudAgentEntry(
                        id=event.tool_call_id,
                        subagent_type=subagent_type,
                        description=desc,
                        model=model_val or None,
                        status="running",
                        start_time=time.monotonic(),
                    )

                    # Keep HUD bounded (avoid unbounded growth during long sessions).
                    if len(self._hud_agent_entries) > self._hud_max_agent_entries:
                        keep = sorted(
                            self._hud_agent_entries.values(), key=lambda a: a.start_time
                        )[-self._hud_max_agent_entries :]
                        self._hud_agent_entries = {a.id: a for a in keep}

            case AgentEventType.TOOL_RESULT:
                hud_only = getattr(event, "hud_only", False)
                hud_dirty = False
                if is_visible_session:
                    if (
                        event.tool_call_id
                        and event.tool_call_id in self._hud_running_tools
                        and bool(event.tool_done)
                    ):
                        del self._hud_running_tools[event.tool_call_id]
                        hud_dirty = True
                    if bool(event.tool_done) and event.tool_name:
                        if event.tool_name not in _HUD_AGENT_TOOLS:
                            self._hud_tool_counts[event.tool_name] = (
                                self._hud_tool_counts.get(event.tool_name, 0) + 1
                            )
                            hud_dirty = True
                        if event.tool_name in _HUD_AGENT_TOOLS and event.tool_call_id:
                            entry = self._hud_agent_entries.get(event.tool_call_id)
                            if entry is not None:
                                entry.status = "completed"
                                entry.end_time = time.monotonic()
                                hud_dirty = True
                if hud_dirty:
                    self._mark_hud_dirty()

                if event.tool_name and not hud_only:
                    message_list.add_tool_result(
                        event.tool_name,
                        event.tool_result or "",
                        event.is_error or False,
                        tool_call_id=event.tool_call_id,
                        done=bool(event.tool_done),
                        stream=event.tool_stream,
                        returncode=event.tool_returncode,
                        elapsed=event.tool_elapsed,
                        timeout=bool(event.tool_timeout),
                    )
                    _mark_background_output()

                # Code Awareness: rescan tree if write created a new directory
                if (
                    is_visible_session
                    and event.tool_name in self._CODE_AWARENESS_FILE_TOOLS
                    and bool(event.tool_done)
                    and not (event.is_error or False)
                ):
                    params_r: Any = getattr(event, "tool_input", None)
                    if isinstance(params_r, dict):
                        fp_r = str(params_r.get("file_path") or params_r.get("path") or "").strip()
                    elif hasattr(event, "tool_result") and event.tool_result:
                        fp_r = ""
                    else:
                        fp_r = ""
                    if fp_r:
                        self._code_awareness_rescan_if_needed(fp_r)

            case AgentEventType.RESPONSE:
                msg = event.message
                if msg:
                    message_list.finalize_message(msg)
                    self._clawteam_last_response_store()[session_id] = msg.content or ""
                    try:
                        self._maybe_finalize_clawteam_deeploop_from_assistant(session_id, msg.content or "")
                    except Exception:
                        _logger.exception("clawteam deeploop finalize hook failed")
                    # Continue deep loop only after run lock is released in _process_message.finally.
                    self.call_later(lambda sid=session_id: self._continue_clawteam_deep_loop_if_needed(sid))
                elif run_state is not None and run_state.build_task_index >= 0:
                    message_list.finalize_message()

                if run_state is not None and run_state.is_plan_run and msg:
                    plan_state = self._get_plan_state(session_id, create=True)
                    if plan_state is not None and self._plan_store is not None:
                        plan_text = msg.content or ""
                        tasks = split_plan_to_tasks(plan_text)
                        if run_state.plan_artifact_scope == "multi-plan":
                            title_hint = self._extract_plan_title(plan_text, run_state.plan_user_request)
                            bundle = self._plan_store.save_bundle_versioned(
                                session_id=session_id,
                                user_request=run_state.plan_user_request,
                                plan_text=plan_text,
                                tasks=tasks,
                                subdir="multi-plan",
                                base_name=title_hint,
                            )
                        elif run_state.plan_artifact_scope == "multi-execute":
                            title_hint = self._extract_plan_title(plan_text, run_state.plan_user_request)
                            bundle = self._plan_store.save_bundle_versioned(
                                session_id=session_id,
                                user_request=run_state.plan_user_request,
                                plan_text=plan_text,
                                tasks=tasks,
                                subdir="multi-execute",
                                base_name=title_hint,
                            )
                        else:
                            bundle = self._plan_store.save_bundle(
                                session_id=session_id,
                                user_request=run_state.plan_user_request,
                                plan_text=plan_text,
                                tasks=tasks,
                            )
                        if isinstance(run_state.plan_routing_meta, dict) and run_state.plan_routing_meta:
                            bundle.routing_meta = dict(run_state.plan_routing_meta)
                            self._plan_store.save_plan_bundle(bundle)
                        plan_state.mode = "plan_ready"
                        plan_state.last_plan_text = plan_text
                        plan_state.last_plan_path = bundle.markdown_path
                        plan_state.last_user_request = run_state.plan_user_request
                        plan_state.bundle = bundle
                        self._sync_hud_todos_from_plan(plan_state)
                        self._refresh_plan_panel(session_id)
                        asyncio.create_task(
                            self._fire_plan_hook(
                                "PlanReady",
                                {
                                    "session_id": session_id,
                                    "plan_path": bundle.markdown_path,
                                },
                            )
                        )
                elif (
                    run_state is not None
                    and msg
                    and (run_state.response_artifact_subdir or "").strip()
                    and self._plan_store is not None
                    and not run_state.is_plan_run
                ):
                    plan_text = msg.content or ""
                    tasks = split_plan_to_tasks(plan_text)
                    title_hint = self._extract_plan_title(plan_text, run_state.plan_user_request)
                    bundle = self._plan_store.save_bundle_versioned(
                        session_id=session_id,
                        user_request=run_state.plan_user_request,
                        plan_text=plan_text,
                        tasks=tasks,
                        subdir=(run_state.response_artifact_subdir or "").strip(),
                        base_name=title_hint,
                    )
                    if isinstance(run_state.plan_routing_meta, dict) and run_state.plan_routing_meta:
                        bundle.routing_meta = dict(run_state.plan_routing_meta)
                        self._plan_store.save_plan_bundle(bundle)
                    run_state.response_artifact_subdir = ""
                elif run_state is not None and run_state.build_task_index >= 0:
                    plan_state = self._get_plan_state(session_id, create=True)
                    if plan_state is not None and plan_state.bundle is not None:
                        idx = run_state.build_task_index
                        if 0 <= idx < len(plan_state.bundle.tasks):
                            task_item = plan_state.bundle.tasks[idx]
                            task_item.status = "completed"
                            summary_src = (msg.content if msg else "") or ""
                            task_item.result_summary = summary_src.strip()[:400]
                            task_key = task_item.id or f"task-{idx + 1}"
                            plan_state.bundle.execution.retry_count_by_task.pop(task_key, None)
                            plan_state.bundle.execution.last_error = ""
                            plan_state.bundle.execution.interrupted = False
                            plan_state.bundle.execution.last_progress_at = int(time.time())
                            if self._plan_store:
                                self._plan_store.save_plan_bundle(plan_state.bundle)
                            self._sync_hud_todos_from_plan(plan_state)
                            self._refresh_plan_panel(session_id)
                        # Chain next build step from _process_message.finally so
                        # is_processing is cleared before _start_agent_run runs.
                elif run_state is not None and run_state.is_plan_run is False and msg:
                    plan_state = self._get_plan_state(session_id, create=True)
                    if plan_state is not None and plan_state.mode == "executing_from_plan":
                        plan_state.mode = "normal"

                if is_visible_session:
                    await self._sync_session_metrics()
                    self._update_status_bars()
                    await self._update_info_panel()
                else:
                    _mark_background_output()

            case AgentEventType.ERROR:
                if event.error:
                    message_list.add_error(str(event.error))
                    if run_state is not None:
                        run_state.last_error = str(event.error)
                        if run_state.build_task_index >= 0:
                            self._handle_build_task_failure(
                                session_id,
                                run_state.build_task_index,
                                str(event.error),
                                allow_auto_retry=True,
                            )
                    _mark_background_output()

    def action_new_session(self) -> None:
        """Create a new session (bound to Ctrl+N)."""
        asyncio.create_task(self._create_new_session())

    async def _create_new_session(self) -> None:
        """Create a new session."""
        if not self._session_service:
            return

        # Create new session
        session = await self._session_service.create("New Chat")
        self.current_session_id = session.id
        self._current_session_title = session.title
        try:
            self.app.current_session_id = session.id
        except Exception:
            pass
        self._get_ui_state(session.id, create=True)
        self._get_run_state(session.id, create=True)
        self._get_plan_state(session.id, create=True)
        self._refresh_plan_panel(session.id)

        # New session => reset HUD dynamic counters.
        self._hud_tool_counts.clear()
        self._hud_agent_entries.clear()
        self._hud_todos.clear()
        self._hud_task_id_to_index.clear()
        self._hud_running_tools.clear()
        self._hud_turn_input_tokens = 0
        self._hud_turn_output_tokens = 0
        self._hud_turn_output_chars = 0

        # Code Awareness: archive old session, clear for new
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
            cap.set_active_session(session.id)
            cap.clear_session()
        except Exception:
            pass

        message_list = self._ensure_message_list(session.id)
        for sid, ui_state in self._session_ui.items():
            if ui_state.message_list is not None:
                ui_state.message_list.display = sid == session.id
        message_list.clear()
        message_list.add_welcome_message(
            context=await self._build_welcome_context(session.id),
        )
        ui_state = self._get_ui_state(session.id, create=False)
        if ui_state is not None:
            ui_state.history_loaded = True

        # Update sidebar
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.set_selected_session(self.current_session_id)
        sidebar.set_session_unread(self.current_session_id, False)
        await sidebar.refresh_sessions()

        # Refresh metrics + status bars
        await self._sync_session_metrics()
        self._update_status_bars()
        await self._update_info_panel()

    def action_open_external_editor(self) -> None:
        """Open external editor for input (bound to Ctrl+E)."""
        import os
        import subprocess
        import tempfile

        try:
            input_widget = self._get_active_input()
        except Exception:
            input_widget = self.query_one("#message_input_widget", MessageInput)

        # Get current content
        content = input_widget.text

        # Create temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Prefer config, then EDITOR env
            editor_cfg = getattr(self.settings.tui, "external_editor", "") or ""
            parts = (editor_cfg.strip() or os.environ.get("EDITOR", "vim")).split()
            cmd = (parts + [temp_path]) if parts else ["vim", temp_path]
            subprocess.run(cmd)

            # Read result
            with open(temp_path, encoding="utf-8") as f:
                input_widget.text = f.read()

            input_widget.focus()

        except Exception:
            self.app.bell()
            input_widget.text = content  # Restore original
        finally:
            # Clean up
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _open_clawcode_json_external_editor(self) -> None:
        """Open workspace or discovered ``.clawcode.json`` in the configured external editor."""
        import os
        import subprocess

        from pathlib import Path

        from ...config.settings import Settings as SettingsCls

        wd = Path(str(getattr(self.settings, "working_directory", "") or ".")).expanduser().resolve()
        cfg = wd / ".clawcode.json"
        if not cfg.is_file():
            found = SettingsCls._find_config_file()
            if found is not None and found.is_file():
                cfg = found
        if not cfg.is_file():
            try:
                self.app.notify(
                    f"No `.clawcode.json` found (looked under `{wd}`). Create one to edit settings.",
                    timeout=5,
                )
            except Exception:
                pass
            return
        editor_cfg = getattr(self.settings.tui, "external_editor", "") or ""
        default_ed = "notepad" if os.name == "nt" else "vim"
        parts = (editor_cfg.strip() or os.environ.get("EDITOR", default_ed)).split()
        cmd = (parts + [str(cfg)]) if parts else [default_ed, str(cfg)]
        try:
            subprocess.run(cmd, check=False)
        except Exception:
            self.app.bell()

    def action_toggle_code_awareness_history(self) -> None:
        """Toggle Code Awareness history summary/full mode."""
        try:
            cap = self.query_one("#code_awareness_panel", CodeAwarenessPanel)
            expanded = cap.toggle_history_expanded()
            mode = "full" if expanded else "summary"
            self.app.notify(f"Code Awareness history: {mode}", timeout=2)
        except Exception:
            pass

    def action_open_file_picker(self) -> None:
        """Open file picker dialog (bound to Ctrl+F).

        Uses ``settings.working_directory`` (from CLI ``-c`` / ``--cwd``), not
        ``os.getcwd()``, so the default folder matches the target project when the
        TUI is launched from another directory (e.g. ClawCode source tree).
        """
        wd = Path(str(getattr(self.settings, "working_directory", "") or ".")).expanduser().resolve()
        self.app.push_screen(
            FilePickerDialog(current_dir=str(wd)),
            callback=self._handle_file_picker_result,
        )

    def _handle_file_picker_result(self, result: Any) -> None:
        """Handle the result from the file picker dialog.

        Args:
            result: Selected files or None
        """
        if result is None:
            return

        if isinstance(result, list) and result:
            # Add attachments to the input widget
            try:
                input_widget = self._get_active_input()
            except Exception:
                input_widget = self.query_one("#message_input_widget", MessageInput)
            input_widget.add_attachments(result)
            input_widget.focus()

    def action_cancel_input(self) -> None:
        """Cancel/clear the current input."""
        if self.current_session_id:
            run_state = self._get_run_state(self.current_session_id, create=False)
            if run_state and run_state.is_processing and run_state.build_task_index >= 0:
                self._stop_plan_build(self.current_session_id)
                return
        try:
            input_widget = self._get_active_input()
        except Exception:
            input_widget = self.query_one("#message_input_widget", MessageInput)
        input_widget.clear()
        input_widget.focus()

    def action_enter_insert_mode(self) -> None:
        """Enter insert mode (focus input)."""
        self._focus_active_input()

    def action_exit_insert_mode(self) -> None:
        """Exit insert mode."""
        # Just remove focus from input
        self.set_focus(None)

    # Actions

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()

    def action_show_help(self) -> None:
        """Show help dialog."""
        from .help import HelpScreen

        self.app.push_screen(HelpScreen())

    def set_display_mode(self, mode: str) -> None:
        """Called by the App when user switches display mode."""
        self._apply_display_mode(mode)
        self.call_later(self._apply_saved_right_panel_width)
        self._focus_active_input()
        self._update_status_bars()
        asyncio.create_task(self._update_info_panel())

    def action_show_display_mode(self) -> None:
        """Open display mode selector dialog."""
        def on_done(result: str | None) -> None:
            if not result:
                return
            self.set_display_mode(result)
            # Persist preference via App if possible
            save = getattr(self.app, "_save_ui_preferences", None)
            if callable(save):
                try:
                    save(display_mode=result)
                except Exception:
                    pass
            try:
                self.app.display_mode = result
            except Exception:
                pass

        current = getattr(self, "_display_mode", "opencode")
        self.app.push_screen(DisplayModeDialog(current_mode=current), callback=on_done)


# Import after definition to avoid circular imports
from ...config import Settings

