"""Built-in slash commands for clawcode TUI (registry, parse, filter)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# Same token rules as plugin/slash._PLUGIN_HEAD (single head segment).
_SLASH_HEAD = re.compile(r"^/([a-zA-Z][a-zA-Z0-9_.-]*)\s*(.*)$", re.DOTALL)

BUILTIN_SLASH_COMMANDS: list[tuple[str, str]] = [
    (
        "init",
        "Initialize CLAWCODE.md (or CLAW.md-style) codebase documentation in the project",
    ),
    (
        "todos",
        "List current todo items",
    ),
    (
        "upgrade",
        "Upgrade tier / rate limits (clawcode is provider-based; no built-in subscription)",
    ),
    (
        "usage",
        "Show context and token usage (HUD-aligned limits)",
    ),
    (
        "vim",
        "Toggle between Vim (Normal) and Insert editing modes",
    ),
    (
        "debug",
        "Debug your current clawcode session via logs (bundled viewer)",
    ),
    (
        "insights",
        "Generate a report analyzing your clawcode sessions",
    ),
    (
        "pr-comments",
        "Get comments from a GitHub pull request",
    ),
    (
        "review",
        "Review a pull request",
    ),
    (
        "code-review",
        "Review local uncommitted changes with severity-ranked findings and commit gate",
    ),
    (
        "security-review",
        "Complete a security review of the pending changes on the current branch",
    ),
    (
        "statusline",
        "Set up clawcode's status line UI",
    ),
    (
        "stats",
        "Show your clawcode usage statistics and activity",
    ),
    (
        "status",
        "Show clawcode status: version, model, workspace, connectivity hints, tools",
    ),
    (
        "stickers",
        "Order clawcode stickers (community / fun)",
    ),
    (
        "tasks",
        "List and manage background tasks (plan build, agent run)",
    ),
    (
        "terminal-setup",
        "Newlines in input: use backslash + Enter (Shift+Enter varies by terminal)",
    ),
    (
        "theme",
        "Change the theme",
    ),
    (
        "release-notes",
        "View release notes",
    ),
    (
        "rename",
        "Rename the current conversation",
    ),
    (
        "resume",
        "Resume a previous conversation",
    ),
    (
        "rewind",
        "Soft-archive chat after a message, or inspect/restore tracked git files (see /rewind help)",
    ),
    (
        "checkpoint",
        "Git workflow checkpoints: create|verify|list|clear (see /checkpoint help)",
    ),
    (
        "skills",
        "List available skills",
    ),
    (
        "memory",
        "Edit claw memory files",
    ),
    (
        "mobile",
        "Show QR code to download the claw mobile app",
    ),
    (
        "model",
        "Set the AI model for clawcode",
    ),
    (
        "output-style",
        "Set the output style directly or from a selection menu",
    ),
    (
        "ui-style",
        "Manage UI style mode, selection, and auto-pick behavior",
    ),
    (
        "permissions",
        "Manage allow & deny tool permission rules",
    ),
    (
        "ide",
        "Manage IDE integrations and show status",
    ),
    (
        "install-github-app",
        "Set up claw GitHub Actions for a repository",
    ),
    (
        "install-slack-app",
        "Install the claw Slack app",
    ),
    (
        "login",
        "Sign in with your Anthropic account",
    ),
    (
        "logout",
        "Sign out from your Anthropic account",
    ),
    (
        "claude",
        "Enable Claw mode (/claw) then path A: Anthropic + Claude Code HTTP identity (see CLAW_SUPPORT_MAP)",
    ),
    (
        "claude-cli",
        "Enable Claw mode (/claw) then path B: run claude / claude-code CLI in workspace",
    ),
    (
        "opencode-cli",
        "Enable Claw mode (/claw) then path B′: run OpenCode opencode CLI in workspace",
    ),
    (
        "codex-cli",
        "Enable Claw mode (/claw) then path B″: run OpenAI Codex CLI in workspace",
    ),
    (
        "mcp",
        "Manage MCP servers",
    ),
    (
        "exit",
        "Exit the REPL",
    ),
    (
        "export",
        "Export the current conversation to a file or clipboard",
    ),
    (
        "fast",
        "Toggle fast mode (use model and token settings in clawcode)",
    ),
    (
        "fork",
        "Create a fork of the current conversation at this point",
    ),
    (
        "help",
        "Show help and available commands",
    ),
    (
        "hooks",
        "Manage hook configurations for tool events",
    ),
    (
        "context",
        "Visualize current context usage as a colored grid",
    ),
    (
        "copy",
        "Copy claw's last response to clipboard as markdown",
    ),
    (
        "cost",
        "Show the total cost and duration of the current session",
    ),
    (
        "desktop",
        "Continue the current session in claw Desktop",
    ),
    (
        "diff",
        "View uncommitted changes and per-turn diffs",
    ),
    (
        "doctor",
        "Diagnose and verify your clawcode installation and settings",
    ),
    (
        "add-dir",
        "Add a new working directory",
    ),
    (
        "agents",
        "Manage agent configurations",
    ),
    (
        "chrome",
        "Claw in Chrome (Beta) settings",
    ),
    (
        "clear",
        "Clear conversation history and free up context",
    ),
    (
        "compact",
        "Clear conversation history but keep a summary in context",
    ),
    (
        "config",
        "Open config panel",
    ),
    (
        "tdd",
        "Run strict TDD workflow: scaffold, RED, GREEN, refactor, and coverage gate",
    ),
    (
        "architect",
        "Run architecture design/review workflow with trade-off analysis and ADR/checklist options",
    ),
    (
        "clawteam",
        "Run multi-role task orchestration, or target one role via /clawteam:<agent>",
    ),
    (
        "clawteam-deeploop-finalize",
        "Parse DEEP_LOOP_WRITEBACK_JSON from pasted or last assistant text using pending deep-loop session metadata",
    ),
    (
        "multi-plan",
        "Run multi-model collaborative planning workflow (plan-only)",
    ),
    (
        "multi-execute",
        "Run multi-model collaborative execution workflow with traceable artifacts",
    ),
    (
        "multi-backend",
        "Run backend-focused multi-model workflow (research through review, orchestrator writes code)",
    ),
    (
        "multi-frontend",
        "Run frontend-focused multi-model workflow (UI/UX led, orchestrator writes code)",
    ),
    (
        "multi-workflow",
        "Run full-stack multi-model workflow (backend + UI advisors, orchestrator writes code)",
    ),
    (
        "orchestrate",
        "Run sequential multi-role workflow (HANDOFF between planner/TDD/review/security/architect); `/orchestrate show|list`",
    ),
    (
        "learn",
        "Learn reusable instincts from recent tool observations",
    ),
    (
        "learn-orchestrate",
        "Run observe -> evolve -> import-to-skill-store orchestration in one command",
    ),
    (
        "experience-dashboard",
        "Show ECAP-first experience metrics dashboard (add --json or --no-alerts)",
    ),
    (
        "closed-loop-contract",
        "Show closed-loop config contract coverage (consumed vs unconsumed keys)",
    ),
    (
        "instinct-status",
        "Show learned instincts grouped by domain and confidence",
    ),
    (
        "instinct-import",
        "Import instincts from local file or URL into inherited set",
    ),
    (
        "instinct-export",
        "Export instincts with optional domain/confidence filters",
    ),
    (
        "evolve",
        "Cluster instincts and optionally generate evolved structures",
    ),
    (
        "experience-create",
        "Create an ECAP experience capsule from recent observations/instincts",
    ),
    (
        "experience-status",
        "List available ECAP capsules with optional filters",
    ),
    (
        "experience-export",
        "Export an ECAP capsule as JSON/Markdown for model or human use",
    ),
    (
        "experience-import",
        "Import an ECAP capsule from local file or URL",
    ),
    (
        "experience-apply",
        "Apply an ECAP capsule as one-shot agent prompt context",
    ),
    (
        "experience-feedback",
        "Record success/failure feedback score for an ECAP capsule",
    ),
    (
        "team-experience-create",
        "Create a TECAP team-experience capsule from collaborative traces",
    ),
    (
        "team-experience-status",
        "List TECAP capsules with optional team/problem filters",
    ),
    (
        "team-experience-export",
        "Export a TECAP capsule as JSON/Markdown for agents and humans",
    ),
    (
        "team-experience-import",
        "Import a TECAP capsule from local file or URL",
    ),
    (
        "team-experience-apply",
        "Apply a TECAP capsule as collaboration context prompt",
    ),
    (
        "team-experience-feedback",
        "Record feedback score for a TECAP capsule",
    ),
    (
        "tecap-create",
        "Alias of /team-experience-create",
    ),
    (
        "tecap-status",
        "Alias of /team-experience-status",
    ),
    (
        "tecap-export",
        "Alias of /team-experience-export",
    ),
    (
        "tecap-import",
        "Alias of /team-experience-import",
    ),
    (
        "tecap-apply",
        "Alias of /team-experience-apply",
    ),
    (
        "tecap-feedback",
        "Alias of /team-experience-feedback",
    ),
]

BUILTIN_SLASH_NAMES: frozenset[str] = frozenset(name for name, _ in BUILTIN_SLASH_COMMANDS)

# Shown in `/` autocomplete only; send path stays on plugin `dispatch_slash` (not built-in handler).
# `plan` is handled in ChatScreen before built-ins; listed here for autocomplete only.
SLASH_AUTOCOMPLETE_EXTRA: list[tuple[str, str]] = [
    ("plugin", "Manage clawcode plugins"),
    (
        "plan",
        "Enable plan mode or view the current session plan",
    ),
    (
        "arc-plan",
        "Generate a one-shot alternative implementation plan (ARC planner)",
    ),
    (
        "claw",
        "Enable Claw agent mode (Claw branch / run_claw_turn) or show status",
    ),
]

_SLASH_SUGGEST_EXACT_HIDE: frozenset[str] = frozenset(
    list(BUILTIN_SLASH_NAMES) + [n for n, _ in SLASH_AUTOCOMPLETE_EXTRA]
)


def slash_autocomplete_hidden_union(skill_rows: list[tuple[str, str]] | None) -> frozenset[str]:
    """Names that count as a complete first token for slash UI (hide suggestion panel)."""
    if not skill_rows:
        return _SLASH_SUGGEST_EXACT_HIDE
    return _SLASH_SUGGEST_EXACT_HIDE | frozenset(n for n, _ in skill_rows)


@dataclass
class BuiltinSlashContext:
    """HUD-aligned snapshot for slash handlers (built by ChatScreen)."""

    todos: list[tuple[str, str]] = field(default_factory=list)
    context_percent: int = 0
    context_window_size: int = 0
    session_prompt_tokens: int = 0
    session_completion_tokens: int = 0
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0
    model_label: str = ""
    app_version: str = ""
    working_dir_display: str = ""
    session_id: str = ""
    session_title: str = ""
    lsp_on: bool = False
    mouse_on: bool = False
    auto_compact: bool = True
    provider_label: str = ""
    is_agent_processing: bool = False
    display_mode: str = ""
    plan_background_tasks: list[str] = field(default_factory=list)
    #: True when /plan is pending in a way that conflicts with Claw mode.
    plan_blocks_claw: bool = False
    #: True when this chat session has Claw mode enabled (for /doctor desktop checks).
    claw_mode_enabled: bool = False
    #: UI style forcing mode for this session.
    ui_style_mode: str = "off"
    #: Currently selected UI style slug for this session.
    ui_style_selected: str = ""
    #: Last UI style selection reason for `/ui-style why`.
    ui_style_reason: str = ""
    #: Last top-k auto candidates for `/ui-style why`.
    ui_style_top_candidates: list[str] = field(default_factory=list)
    #: How the current UI style was chosen (e.g. auto, user).
    ui_style_source: str = ""


def parse_slash_line(text: str) -> tuple[str | None, str]:
    """Parse leading `/command` and tail. Returns (None, original) if not a slash command."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, raw
    m = _SLASH_HEAD.match(raw)
    if not m:
        return None, raw
    return m.group(1), m.group(2).strip()


def slash_suggest_query(
    text: str,
    *,
    autocomplete_hidden: frozenset[str] | None = None,
) -> str | None:
    """If the first line is an incomplete `/prefix` command (no space after name), return prefix after `/`.

    Returns None when suggestions should be hidden (normal message or finished command token).

    ``autocomplete_hidden``: when set, treat these names as complete commands (hide panel), e.g. plugin skill names.
    """
    if not text:
        return None
    first = text.split("\n", 1)[0]
    if not first.startswith("/"):
        return None
    rest = first[1:]
    if " " in rest:
        return None
    hidden = autocomplete_hidden if autocomplete_hidden is not None else _SLASH_SUGGEST_EXACT_HIDE
    if rest in hidden:
        return None
    return rest


def filter_commands(
    query: str,
    extra: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Filter built-ins by command name prefix (case-sensitive, as typed).

    ``extra``: optional (name, description) pairs from plugin skills, appended after built-ins (deduped by name).
    """
    q = query or ""
    merged = list(BUILTIN_SLASH_COMMANDS) + SLASH_AUTOCOMPLETE_EXTRA
    if extra:
        seen = {n for n, _ in merged}
        for n, d in extra:
            if n not in seen:
                merged.append((n, d))
                seen.add(n)
    out = [(n, d) for n, d in merged if n.startswith(q)]
    return out


def longest_common_prefix(names: list[str]) -> str:
    if not names:
        return ""
    s1 = min(names)
    s2 = max(names)
    for i, (a, b) in enumerate(zip(s1, s2, strict=False)):
        if a != b:
            return s1[:i]
    return s1[: min(len(s1), len(s2))]


BuiltinSlashOutcomeKind = Literal["assistant_message", "agent_prompt"]
BuiltinSlashUiAction = Literal[
    None,
    "toggle_vim",
    "show_theme_selector",
    "show_rename_dialog",
    "switch_session",
    "reload_session_history",
    "confirm_git_restore",
    "open_model_dialog",
    "open_display_mode",
    "exit_app",
    "show_help_screen",
    "open_clawcode_config_external",
    "enable_claw_mode",
]


class BuiltinSlashOutcome:
    """Result of handling a built-in slash command."""

    __slots__ = (
        "kind",
        "assistant_text",
        "agent_user_text",
        "ui_action",
        "git_restore_cwd",
        "git_restore_paths",
        "apply_display_mode",
        "clear_session_tool_permissions",
        "clipboard_text",
        "switch_to_session_id",
        "routing_meta",
        "clawteam_deeploop_meta",
    )

    def __init__(
        self,
        *,
        kind: BuiltinSlashOutcomeKind,
        assistant_text: str | None = None,
        agent_user_text: str | None = None,
        ui_action: BuiltinSlashUiAction = None,
        git_restore_cwd: str | None = None,
        git_restore_paths: list[str] | None = None,
        apply_display_mode: str | None = None,
        clear_session_tool_permissions: bool = False,
        clipboard_text: str | None = None,
        switch_to_session_id: str | None = None,
        routing_meta: dict | None = None,
        clawteam_deeploop_meta: dict | None = None,
    ) -> None:
        self.kind = kind
        self.assistant_text = assistant_text
        self.agent_user_text = agent_user_text
        self.ui_action: BuiltinSlashUiAction = ui_action
        self.git_restore_cwd = git_restore_cwd
        self.git_restore_paths = git_restore_paths
        self.apply_display_mode = apply_display_mode
        self.clear_session_tool_permissions = clear_session_tool_permissions
        self.clipboard_text = clipboard_text
        self.switch_to_session_id = switch_to_session_id
        self.routing_meta = routing_meta or {}
        self.clawteam_deeploop_meta = clawteam_deeploop_meta
