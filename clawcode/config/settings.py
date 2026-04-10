"""Configuration management using Pydantic.

This module provides settings management with validation and
environment variable support.
"""

from __future__ import annotations

import json
import logging
from enum import Enum  # Keep for potential future use
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .constants import (
    AgentName,
    DEFAULT_CONTEXT_PATHS,
    DEFAULT_DATA_DIRECTORY,
    DEFAULT_MAX_TOKENS,
    FinishReason,
    MCPType,
    MessageRole,
    ModelProvider,
)


class MCPServer(BaseModel):
    """MCP server configuration."""

    command: str = ""
    env: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    type: MCPType = MCPType.STDIO
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class Provider(BaseModel):
    """LLM provider configuration."""

    api_key: str | None = None
    disabled: bool = False
    base_url: str | None = None
    timeout: int = 120
    # Optional list for the model picker (Ctrl+O). When empty, the TUI infers
    # candidates from agents.*.provider_key and reference_providers (mirrors .clawcode.json).
    models: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Agent configuration."""

    model: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    temperature: float | None = None
    # Optional provider config slot key (selects an entry in Settings.providers).
    # Example: "openai_compat", "claude_proxy", etc.
    provider_key: str | None = None


import os
import platform
import shutil

logger = logging.getLogger(__name__)


def default_shell_path() -> str:
    """Default shell for the bash tool: PowerShell on Windows when available, else cmd; bash on POSIX."""

    if platform.system() == "Windows":
        for candidate in ("pwsh", "powershell", "powershell.exe"):
            if shutil.which(candidate):
                return candidate
        return "cmd.exe"
    return "/bin/bash"


class ShellConfig(BaseModel):
    """Shell configuration for bash tool.

    On Windows, defaults to ``pwsh``/``powershell`` when on PATH, else ``cmd.exe``.
    PowerShell is invoked via ``-Command`` (not ``shell=True``). Use ``path: cmd.exe``
    to force classic cmd. On Unix, default is ``/bin/bash``. Extra ``args`` are
    inserted before ``-c`` / ``-Command``.

    When ``prefer_git_bash_on_windows`` is True (default), the bash tool tries
    Git for Windows' ``bash.exe`` first (see ``CLAWCODE_GIT_BASH_PATH`` or the
    legacy compatibility env key used by ``local.find_bash``), using POSIX command expansion; if bash is missing
    or the process cannot be started, it falls back to ``path``/``args`` above.

    ``bash_python_fallback`` enables a small Python re-run for whitelisted commands
    when the subprocess fails with typical WSL/store noise; use
    ``bash_python_fallback_without_env_hint`` to also retry on any non-zero exit
    when the command shape matches the whitelist.

    When ``use_environments_backend`` is True, the bash tool uses
    ``clawcode.llm.tools.environments.create_environment`` and
    ``BaseEnvironment.execute_async`` instead of asyncio subprocesses. Backend type
    is ``terminal_env`` unless the environment variable ``CLAWCODE_TERMINAL_ENV`` is
    set (only read when ``use_environments_backend`` is True). Each invocation uses
    ``persistent=False`` for the ``local`` backend so behavior matches one-shot runs.
    """

    path: str = Field(default_factory=default_shell_path)
    args: list[str] = Field(default_factory=list)
    prefer_git_bash_on_windows: bool = True
    #: When True and the bash subprocess exits non-zero, try a small whitelist of
    #: commands in Python (see ``bash_fallback``) if output looks like a WSL/store
    #: stub failure or ``bash_python_fallback_without_env_hint`` is enabled.
    bash_python_fallback: bool = True
    #: If True, allow Python fallback on any non-zero exit when the command matches
    #: a whitelist pattern (not only WSL/Microsoft Store style stderr).
    bash_python_fallback_without_env_hint: bool = False
    #: Delegate bash runs to ``create_environment`` + ``execute_async`` (see package docstring).
    use_environments_backend: bool = False
    #: ``env_type`` for ``create_environment`` when ``use_environments_backend`` is True.
    terminal_env: str = "local"


class PluginConfig(BaseModel):
    """Plugin configuration (Claude Code compatible).

    ``data_root_mode`` selects where plugin data lives (mirrors Claude Code's
    ``~/.claude`` layout: ``plugins/``, ``plugins/cache``, ``plugin-state.json``).
    """

    enabled: bool = True
    plugin_dirs: list[str] = Field(default_factory=list)
    disabled_plugins: list[str] = Field(default_factory=list)
    # clawcode -> ~/.clawcode; claude -> ~/.claude; custom -> plugins_data_root
    data_root_mode: Literal["clawcode", "claude", "custom"] = "clawcode"
    # When data_root_mode is custom: absolute path to the plugin data root
    # (same layout as ~/.clawcode: plugins/, marketplaces/, plugin-state.json).
    plugins_data_root: str | None = None


class LSPConfig(BaseModel):
    """Language Server Protocol configuration."""

    disabled: bool = False
    command: str
    args: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class InputHistoryConfig(BaseModel):
    """Persistent input history settings."""

    enabled: bool = True
    retention_days: float = 7.0
    max_entries: int = 500
    granularity: Literal["project", "global", "session"] = "project"


class TUIConfig(BaseModel):
    """Terminal UI configuration."""

    theme: str = "yellow"  # Default theme: yellow, catppuccin, dracula, gruvbox, monokai, onedark, tokyonight
    display_mode: str = "opencode"  # classic, opencode, clawcode, claude, minimal, zen
    mouse_enabled: bool = True
    save_theme_preference: bool = True  # Save theme preference to disk
    external_editor: str = ""  # e.g. vim, nvim, or $EDITOR; empty = use default
    # Optional UI label override shown in TUI panels (welcome/title/status/info).
    # Example in .clawcode.json: { "tui": { "display_version": "0.1.0" } }
    display_version: str = ""
    input_history: InputHistoryConfig = Field(default_factory=InputHistoryConfig)


class SourcegraphConfig(BaseModel):
    """Sourcegraph instance configuration for code search."""

    url: str = "https://sourcegraph.com"
    access_token: str | None = None
    enabled: bool = False


class DataConfig(BaseModel):
    """Data storage configuration."""

    directory: str = DEFAULT_DATA_DIRECTORY


class WebConfig(BaseModel):
    """Web tooling configuration (used by migrated browser/web tools)."""

    backend: Literal["firecrawl", "parallel", "tavily"] = "firecrawl"


class BrowserConfig(BaseModel):
    """Browser automation configuration (cloud/local backends)."""

    # "browserbase" / "browser-use" (see clawcode.llm.tools.browser.browser_utils)
    cloud_provider: str | None = None


class DesktopConfig(BaseModel):
    """OS desktop automation (Computer Use style: screenshots, mouse/keyboard).

    High-risk: only active when ``enabled`` is true and optional deps
    (``mss``, ``pyautogui``) are installed. See ``docs/CLAW_MODE.md`` (Desktop tools).
    """

    enabled: bool = False
    max_screenshot_width: int = 3840
    max_screenshot_height: int = 2160
    #: ``mss`` monitor index: ``0`` = all screens union, ``1`` = primary (default).
    monitor_index: int = Field(default=1, ge=0, le=32)
    #: When True, TUI only registers ``desktop_*`` while global Claw mode is on (see ``get_builtin_tools(for_claw_mode=...)``). CLI defaults omit filtering.
    tools_require_claw_mode: bool = False
    #: Max desktop tool invocations per rolling minute; ``None`` or ``0`` = unlimited.
    max_actions_per_minute: int | None = None
    #: Rolling limit scope: ``global`` (whole process, default) or ``session`` (per ``ToolContext.session_id``).
    rate_limit_scope: Literal["global", "session"] = "global"
    #: When true, after ``desktop_screenshot`` succeeds the Agent appends a USER message with ``ImageContent`` so vision models see pixels without ``MEDIA:`` (off by default).
    auto_attach_desktop_screenshot: bool = False
    #: Reject ``desktop_key`` when the normalized key spec contains any of these substrings (e.g. ``alt+f4``).
    blocked_hotkey_substrings: list[str] = Field(default_factory=list)


class WebsiteBlocklistConfig(BaseModel):
    """User-controlled URL blocklist policy."""

    enabled: bool = False
    domains: list[str] = Field(default_factory=list)
    shared_files: list[str] = Field(default_factory=list)


class ClosedLoopConfig(BaseModel):
    """Closed-loop learning governance and observability knobs."""

    memory_governance_enabled: bool = True
    #: Capsule JSON retention under learning/experience|team-experience/capsules (newest kept).
    knowledge_max_ecap: int = 200
    knowledge_max_tecap: int = 200
    #: Evolved artifact caps (0 = skip pruning for that bucket). See LearningService._enforce_knowledge_lifecycle.
    knowledge_max_evolved_skill_packages: int = 80
    knowledge_max_evolved_command_md: int = 100
    knowledge_max_evolved_agent_md: int = 100
    flush_budget_enabled: bool = True
    search_rerank_enabled: bool = True
    skill_audit_enabled: bool = True

    memory_default_score: float = 0.5
    memory_legacy_score: float = 0.4
    memory_score_min: float = 0.0
    memory_score_max: float = 1.0

    flush_max_writes: int = 2
    flush_duplicate_suppression: bool = True

    search_weight_base: float = 0.55
    search_weight_role: float = 0.25
    search_weight_recency: float = 0.2
    search_snippet_penalty_cap: float = 0.35
    search_role_weight_user: float = 1.0
    search_role_weight_assistant: float = 0.9
    search_role_weight_system: float = 0.8
    search_role_weight_tool: float = 0.55
    search_role_weight_default: float = 0.6

    observability_enabled: bool = True
    observability_events_file: str = "claw_metrics/events.jsonl"

    tuning_enabled: bool = True
    tuning_auto_apply_enabled: bool = False
    tuning_window_hours: int = 24
    tuning_cooldown_minutes: int = 120
    tuning_layered_enabled: bool = True
    tuning_layer_weight_global: float = 0.2
    tuning_layer_weight_domain: float = 0.3
    tuning_layer_weight_session: float = 0.5
    tuning_report_top_n: int = 8
    tuning_domain_templates: dict[str, dict[str, float | int | bool]] = Field(default_factory=dict)
    tuning_export_reports_enabled: bool = True
    tuning_export_reports_dir: str = "claw_metrics/reports"
    tuning_export_retention_count: int = 50

    # Experience routing weights (ECAP)
    experience_routing_weight_base_score: float = 0.45
    experience_routing_weight_confidence: float = 0.2
    experience_routing_weight_model_scope: float = 0.15
    experience_routing_weight_agent_scope: float = 0.1
    experience_routing_weight_skill_scope: float = 0.1
    experience_routing_penalty_risk_gap: float = 0.15
    experience_routing_penalty_quality_gap: float = 0.05

    # Team routing weights (TECAP)
    team_routing_weight_feedback: float = 0.30
    team_routing_weight_result_bonus: float = 0.18
    team_routing_weight_workflow_match: float = 0.16
    team_routing_weight_problem_match: float = 0.14
    team_routing_weight_team_match: float = 0.10
    team_routing_weight_quality: float = 0.08
    team_routing_weight_recency: float = 0.03
    team_routing_weight_team_experience: float = 0.01
    team_routing_weight_team_scope: float = 0.04

    # Experience -> instinct delta amplitudes
    experience_instinct_delta_ecap_success: float = 0.03
    experience_instinct_delta_ecap_fail: float = -0.04
    experience_instinct_delta_tecap_success: float = 0.02
    experience_instinct_delta_tecap_fail: float = -0.03

    # Experience tuning gate thresholds
    experience_tuning_gate_min_confidence: float = 0.45
    experience_tuning_gate_max_ci_width: float = 0.65
    experience_tuning_gate_min_samples: float = 1.0

    # Evolve instinct->skill optimization toggles
    evolve_experience_gate_enabled: bool = True
    evolve_experience_gate_min_score: float = 0.5
    evolve_experience_gate_min_confidence: float = 0.45
    evolve_experience_gate_max_ci_width: float = 0.65
    evolve_experience_gate_min_samples: float = 1.0
    evolve_experience_enrich_skill_md_enabled: bool = True
    evolve_experience_weighted_cluster_enabled: bool = True
    evolve_experience_weight_trigger: float = 1.0
    evolve_experience_weight_similarity: float = 0.6
    evolve_experience_weight_consistency: float = 0.4

    # ECAP-first dashboard and alerts
    experience_dashboard_enabled: bool = True
    experience_dashboard_window_days: list[int] = Field(default_factory=lambda: [7, 30, 90])
    experience_dashboard_min_samples: int = 3
    experience_alert_enabled: bool = True
    experience_alert_cooldown_minutes: int = 60
    experience_adaptive_policy_enabled: bool = True
    experience_adaptive_policy_cooldown_cycles: int = 3
    experience_adaptive_policy_max_step: float = 0.05
    experience_policy_auto_apply_enabled: bool = False
    experience_policy_auto_apply_cooldown_cycles: int = 3
    experience_ab_enabled: bool = True
    experience_ab_domains: list[str] = Field(default_factory=list)
    clawteam_deeploop_enabled: bool = True
    clawteam_deeploop_max_iters: int = 100
    clawteam_deeploop_min_gap_delta: float = 0.05
    clawteam_deeploop_convergence_rounds: int = 2
    clawteam_deeploop_handoff_target: float = 0.85
    clawteam_deeploop_critical_degrade_enabled: bool = True
    clawteam_deeploop_auto_writeback_enabled: bool = True
    clawteam_deeploop_max_rollbacks: int = 2
    #: When > 0, ``deeploop_convergence_decision_with_alerts`` may stop early if dashboard
    #: ``closed_loop_gain_consistency`` is at or above this threshold.
    clawteam_deeploop_consistency_min: float = 0.0
    experience_alert_thresholds: dict[str, dict[str, float | int]] = Field(
        default_factory=lambda: {
            "ecap_effectiveness_avg": {"warning_lt": 0.55, "critical_lt": 0.45},
            "ecap_confidence_avg": {"warning_lt": 0.50, "critical_lt": 0.40},
            "ecap_ci_width_avg": {"warning_gt": 0.60, "critical_gt": 0.75},
            "ecap_sample_sufficiency_rate": {"warning_lt": 0.60, "critical_lt": 0.40},
            "ecap_gap_convergence": {"warning_drop_gt": 0.03, "critical_drop_gt": 0.08},
            "instinct_delta_net": {"warning_lt": 0.0, "critical_lt": -0.5},
            "experience_gate_block_rate": {"warning_gt": 0.35, "critical_gt": 0.60},
            "routing_experience_contribution": {"warning_lt": 0.30, "critical_lt": 0.20},
            "tuning_experience_gate_pass_rate": {"warning_lt": 0.50, "critical_lt": 0.30},
            "closed_loop_gain_consistency": {"warning_lt": 0.45, "critical_lt": 0.30},
        }
    )


class JSONFileSettingsSource(PydanticBaseSettingsSource):
    """Load settings from a JSON file.

    Parse JSON into a dict and pass it to Pydantic as-is. Pydantic will handle
    nested structures (agents / providers, etc.).
    """

    def __init__(self, json_file: str | Path | None = None):
        self.json_file = json_file
        self._config_data: dict[str, Any] = {}
        if json_file is not None:
            path = Path(json_file)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._config_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._config_data = {}

    def get_field_value(
        self,
        field: Field,
        field_name: str,
    ) -> Any | None:
        """Get the value for a specific field.

        Args:
            field: The field to get the value for
            field_name: The name of the field

        Returns:
            The field value, or None if not found
        """
        if field_name in self._config_data:
            return self._config_data[field_name]

        upper_name = field_name.upper()
        if upper_name in self._config_data:
            return self._config_data[upper_name]

        return None

    def __call__(self, settings: BaseSettings | None = None) -> dict[str, Any]:
        """Return all settings from the JSON file.

        Args:
            settings: The settings instance (optional)

        Returns:
            Dictionary of setting names to values
        """
        return self._config_data


class Settings(BaseSettings):
    """Main application settings.

    Settings are loaded from multiple sources in order:
    1. Default values
    2. JSON config file (.clawcode.json)
    3. Environment variables (CLAWCODE_*)
    """

    model_config = SettingsConfigDict(
        env_prefix="CLAWCODE",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Data
    data: DataConfig = Field(default_factory=DataConfig)

    # Web / Browser tooling (migrated Hermes compatibility)
    web: WebConfig = Field(default_factory=WebConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)
    website_blocklist: WebsiteBlocklistConfig = Field(
        default_factory=WebsiteBlocklistConfig
    )

    # Working directory (set programmatically)
    working_directory: str = Field(default="")

    #: Directory where ``python -m clawcode`` was started (shell cwd). Used with ``-c`` /
    #: ``--cwd`` so UI catalog at the host repo's ``.claw/design/UI/`` is still found
    #: when the target project is another folder.
    cli_launch_directory: str = Field(default="")

    # Providers
    providers: dict[str, Provider] = Field(
        default_factory=lambda: {
            "anthropic": Provider(),
            "openai": Provider(),
            "gemini": Provider(),
        }
    )

    # Agents
    agents: dict[AgentName, AgentConfig] = Field(
        default_factory=lambda: {
            AgentName.CODER: AgentConfig(
                model="claude-3-5-sonnet-20241022",
                max_tokens=8192,
            ),
            AgentName.TASK: AgentConfig(
                model="claude-3-5-sonnet-20241022",
                max_tokens=8192,
            ),
            AgentName.TITLE: AgentConfig(
                model="claude-3-5-haiku-20241022",
                max_tokens=100,
            ),
            AgentName.SUMMARIZER: AgentConfig(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
            ),
        }
    )

    # MCP Servers
    mcp_servers: dict[str, MCPServer] = Field(default_factory=dict)

    # LSP
    lsp: dict[str, LSPConfig] = Field(
        default_factory=lambda: {
            # Systems / compiled languages
            "python": LSPConfig(command="pylsp"),
            "go": LSPConfig(command="gopls", args=["serve"]),
            "typescript": LSPConfig(
                command="typescript-language-server",
                args=["--stdio"],
            ),
            "rust": LSPConfig(command="rust-analyzer"),
            "java": LSPConfig(command="jdtls"),
            "c": LSPConfig(command="clangd"),
            "csharp": LSPConfig(command="omnisharp", args=["-lsp"]),
            "kotlin": LSPConfig(command="kotlin-language-server"),
            "scala": LSPConfig(command="metals"),
            "swift": LSPConfig(command="sourcekit-lsp"),
            "dart": LSPConfig(
                command="dart",
                args=["language-server", "--protocol=lsp"],
            ),
            "zig": LSPConfig(command="zls"),
            # Scripting languages
            "ruby": LSPConfig(command="solargraph", args=["stdio"]),
            "php": LSPConfig(command="intelephense", args=["--stdio"]),
            "lua": LSPConfig(command="lua-language-server"),
            "perl": LSPConfig(command="perlnavigator", args=["--stdio"]),
            "r": LSPConfig(
                command="R",
                args=["--slave", "-e", "languageserver::run()"],
            ),
            # Functional languages
            "haskell": LSPConfig(
                command="haskell-language-server-wrapper",
                args=["--lsp"],
            ),
            "elixir": LSPConfig(command="elixir-ls"),
            "erlang": LSPConfig(command="erlang_ls"),
            "ocaml": LSPConfig(command="ocamllsp"),
            "clojure": LSPConfig(command="clojure-lsp"),
            # Web / frontend
            "html": LSPConfig(
                command="vscode-html-language-server",
                args=["--stdio"],
            ),
            "css": LSPConfig(
                command="vscode-css-language-server",
                args=["--stdio"],
            ),
            "vue": LSPConfig(
                command="vue-language-server",
                args=["--stdio"],
            ),
            "svelte": LSPConfig(command="svelteserver", args=["--stdio"]),
            # Data / config languages
            "json": LSPConfig(
                command="vscode-json-language-server",
                args=["--stdio"],
            ),
            "yaml": LSPConfig(
                command="yaml-language-server",
                args=["--stdio"],
            ),
            "toml": LSPConfig(command="taplo", args=["lsp", "stdio"]),
            "sql": LSPConfig(command="sqls"),
            "graphql": LSPConfig(
                command="graphql-lsp",
                args=["server", "-m", "stream"],
            ),
            # Shell / scripting
            "bash": LSPConfig(
                command="bash-language-server",
                args=["start"],
            ),
            "powershell": LSPConfig(
                command="pwsh",
                args=["-NoLogo", "-NoProfile", "-Command",
                      "Import-Module PowerShellEditorServices; Start-EditorServices -Stdio"],
            ),
            # Infrastructure / DevOps
            "terraform": LSPConfig(
                command="terraform-ls",
                args=["serve"],
            ),
            "dockerfile": LSPConfig(
                command="docker-langserver",
                args=["--stdio"],
            ),
            "protobuf": LSPConfig(
                command="buf",
                args=["beta", "lsp"],
            ),
            # Documentation
            "markdown": LSPConfig(command="marksman", args=["server"]),
            "latex": LSPConfig(command="texlab"),
        }
    )

    # TUI
    tui: TUIConfig = Field(default_factory=TUIConfig)

    # Sourcegraph (optional advanced code search)
    sourcegraph: SourcegraphConfig = Field(default_factory=SourcegraphConfig)

    # Shell
    shell: ShellConfig = Field(default_factory=ShellConfig)

    # Plugins (Claude Code compatible)
    plugins: PluginConfig = Field(default_factory=PluginConfig)

    # Auto Compact
    auto_compact: bool = True

    #: When True and safe (no streaming/subagent tools in the batch, and either no
    #: permission client or every tool is read-only), run multiple tool_calls from
    #: one assistant turn via asyncio.gather.  See docs/PARALLEL_TOOL_CALLS.md.
    parallel_tool_calls: bool = True

    # Context paths for loading project instructions
    context_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_CONTEXT_PATHS))

    # UI style orchestration (coder UI references)
    ui_style_mode: Literal["off", "on"] = "off"
    ui_style_default_slug: str = ""

    # Closed-loop optimization knobs
    closed_loop: ClosedLoopConfig = Field(default_factory=ClosedLoopConfig)

    # Debug
    debug: bool = False
    debug_lsp: bool = False
    debug_llm: bool = False

    #: Background terminal process watcher verbosity (TUI chat inserts). Hermes-compatible
    #: keys: env ``HERMES_BACKGROUND_NOTIFICATIONS`` (override), ``CLAWCODE_BACKGROUND_PROCESS_NOTIFICATIONS``,
    #: or this field in ``.clawcode.json``. Default ``result`` (Hermes defaults to ``all`` when unset there).
    background_process_notifications: Literal["all", "result", "error", "off"] = "result"

    @field_validator("background_process_notifications", mode="before")
    @classmethod
    def _coerce_background_process_notifications(cls, v: Any) -> str:
        if v is False:
            return "off"
        if v is None or v == "":
            return "result"
        s = str(v).strip().lower()
        if s in ("false", "0", "no"):
            return "off"
        if s in ("all", "result", "error", "off"):
            return s
        logger.warning(
            "Unknown background_process_notifications %r, defaulting to result",
            v,
        )
        return "result"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add JSON config file as a source."""
        return (
            init_settings,
            JSONFileSettingsSource(cls._find_config_file()),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @staticmethod
    def _find_config_file() -> Path | None:
        """Find the configuration file.

        Searches in the following order:
        1. ./.clawcode.json
        2. $XDG_CONFIG_HOME/clawcode/.clawcode.json
        3. ~/.clawcode.json
        """
        # Check current directory
        local_config = Path.cwd() / ".clawcode.json"
        if local_config.exists():
            return local_config

        # Check XDG config directory
        xdg_config = Path.home() / ".config" / "clawcode" / ".clawcode.json"
        if xdg_config.exists():
            return xdg_config

        # Check home directory
        home_config = Path.home() / ".clawcode.json"
        if home_config.exists():
            return home_config

        return None

    @field_validator("working_directory", mode="before")
    @classmethod
    def set_working_directory(cls, v: str | None) -> str:
        """Set the working directory to current directory if not set."""
        if v is None or v == "":
            import os

            return os.getcwd()
        return v

    def get_provider_config(self, provider: ModelProvider) -> Provider:
        """Get configuration for a specific provider.

        Args:
            provider: The provider name

        Returns:
            The provider configuration, or a default disabled config
        """
        if provider.value in self.providers:
            return self.providers[provider.value]

        return Provider(disabled=True)

    def get_agent_config(self, agent: AgentName) -> AgentConfig:
        """Get configuration for a specific agent.

        Args:
            agent: The agent name

        Returns:
            The agent configuration, or a default

        Raises:
            KeyError: If the agent is not configured
        """
        if agent in self.agents:
            return self.agents[agent]

        # Return default coder config
        return self.agents.get(AgentName.CODER, AgentConfig(model="claude-3-5-sonnet-20241022"))

    def get_data_directory(self) -> Path:
        """Get the data directory path.

        Returns:
            Path to the data directory
        """
        if Path(self.data.directory).is_absolute():
            return Path(self.data.directory)

        return Path(self.working_directory) / self.data.directory

    def ensure_data_directory(self) -> Path:
        """Ensure the data directory exists.

        Returns:
            Path to the data directory
        """
        data_dir = self.get_data_directory()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir


def save_agent_to_clawcode_json(agent_name: str, config: AgentConfig) -> Path:
    """Merge one agent entry into ``.clawcode.json`` (read–modify–write).

    Uses the same discovery order as :meth:`Settings._find_config_file`. If no
    file exists yet, creates ``./.clawcode.json`` (current working directory).

    Args:
        agent_name: Agent slot name (e.g. ``coder``).
        config: Agent configuration to persist for that slot.

    Returns:
        Path to the file written.

    Raises:
        OSError: If the file cannot be read or written.
        TypeError: If existing JSON root is not an object.
    """
    path = Settings._find_config_file()
    if path is None:
        path = Path.cwd() / ".clawcode.json"

    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw = None
        if raw is None:
            data = {}
        elif isinstance(raw, dict):
            data = raw
        else:
            raise TypeError(f"Config root must be a JSON object, got {type(raw).__name__}")

    agents_obj = data.get("agents")
    agents: dict[str, Any] = dict(agents_obj) if isinstance(agents_obj, dict) else {}
    agents[agent_name] = config.model_dump(mode="json")
    data["agents"] = agents

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return path


def append_context_path_to_clawcode_json(
    directory: str,
    *,
    working_directory: str = ".",
) -> Path:
    """Append a resolved directory path to ``context_paths`` in ``.clawcode.json`` (merge read–write).

    Uses ``<working_directory>/.clawcode.json`` when present, otherwise the first existing
    file from :meth:`Settings._find_config_file`, otherwise creates
    ``<working_directory>/.clawcode.json``.

    Raises:
        ValueError: If ``directory`` is not an existing directory.
        TypeError: If existing JSON root is not an object.
    """
    resolved = Path(directory).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {resolved}")
    norm = str(resolved).replace("\\", "/")
    wd = Path(working_directory).expanduser().resolve()
    path = wd / ".clawcode.json"
    if not path.is_file():
        alt = Settings._find_config_file()
        path = alt if alt is not None else path

    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw = None
        if raw is None:
            data = {}
        elif isinstance(raw, dict):
            data = raw
        else:
            raise TypeError(f"Config root must be a JSON object, got {type(raw).__name__}")

    paths_raw = data.get("context_paths")
    paths: list[Any] = list(paths_raw) if isinstance(paths_raw, list) else []
    if norm not in paths:
        paths.append(norm)
    data["context_paths"] = paths

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return path


def save_ui_style_mode_to_clawcode_json(
    mode: Literal["off", "on"],
    *,
    working_directory: str = ".",
) -> Path:
    """Persist ``ui_style_mode`` in ``.clawcode.json`` using merge read/write."""
    wd = Path(working_directory).expanduser().resolve()
    path = wd / ".clawcode.json"
    if not path.is_file():
        alt = Settings._find_config_file()
        path = alt if alt is not None else path
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw = None
        if raw is None:
            data = {}
        elif isinstance(raw, dict):
            data = raw
        else:
            raise TypeError(f"Config root must be a JSON object, got {type(raw).__name__}")
    data["ui_style_mode"] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings instance.

    Returns:
        The settings instance

    Raises:
        RuntimeError: If settings haven't been loaded
    """
    global _settings
    if _settings is None:
        raise RuntimeError("Settings not loaded. Call load_settings() first.")
    return _settings


async def load_settings(
    working_directory: str | None = None,
    debug: bool = False,
) -> Settings:
    """Load settings from all sources.

    Args:
        working_directory: Override the working directory
        debug: Enable debug mode

    Returns:
        The loaded settings
    """
    global _settings

    settings = Settings()

    if working_directory:
        settings.working_directory = working_directory

    if debug:
        settings.debug = True

    _settings = settings
    return settings


def reload_settings() -> Settings:
    """Reload settings from all sources.

    Returns:
        The reloaded settings
    """
    global _settings
    _settings = None
    return Settings()
