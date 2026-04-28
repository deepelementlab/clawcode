from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config.settings import LSPConfig, MCPServer


class PluginManifest(BaseModel):
    """Claude Code plugin.json manifest.

    Unknown fields are preserved. When ``strict`` is true, loaders should use
    manifest-declared paths as the authority for components.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    version: str | None = None
    description: str | None = None
    author: dict[str, Any] | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    strict: bool | None = None

    # Component path fields (can be inline config, a string, or a list of strings)
    commands: str | list[str] | None = None
    agents: str | list[str] | None = None
    skills: str | list[str] | None = None
    hooks: str | dict[str, Any] | None = None
    mcpServers: str | dict[str, Any] | None = None
    outputStyles: str | list[str] | None = None
    lspServers: str | dict[str, Any] | None = None


class SkillContext(str, Enum):
    INLINE = "inline"
    FORK = "fork"


class PluginSkill(BaseModel):
    """A Claude Code skill loaded from SKILL.md."""

    model_config = ConfigDict(extra="ignore")

    # Claude Code: the YAML field `name` becomes the `/slash-command`.
    name: str
    description: str | None = None
    content: str

    plugin_name: str
    disable_model_invocation: bool = False
    argument_hint: str | None = None
    user_invocable: bool | None = None

    # Claude Code supports a number of additional frontmatter fields.
    allowed_tools: list[str] = Field(default_factory=list)
    context: SkillContext = SkillContext.INLINE


class HookEvent(str, Enum):
    # Keep a superset of the events from Claude Code docs that we may map later.
    SessionStart = "SessionStart"
    SessionEnd = "SessionEnd"
    UserPromptSubmit = "UserPromptSubmit"

    PreToolUse = "PreToolUse"
    PostToolUse = "PostToolUse"
    PostToolUseFailure = "PostToolUseFailure"

    PermissionRequest = "PermissionRequest"
    Notification = "Notification"

    Stop = "Stop"
    TaskCompleted = "TaskCompleted"
    TeammateIdle = "TeammateIdle"

    SubagentStart = "SubagentStart"
    SubagentStop = "SubagentStop"
    PlanStart = "PlanStart"
    PlanReady = "PlanReady"
    PlanApproved = "PlanApproved"

    PreCompact = "PreCompact"
    PostCompact = "PostCompact"

    # Research mode (optional plugin hooks)
    ResearchSessionStart = "ResearchSessionStart"
    ResearchSessionEnd = "ResearchSessionEnd"
    ResearchPhaseStart = "ResearchPhaseStart"
    ResearchPlanCreated = "ResearchPlanCreated"
    ResearchSubAgentStart = "ResearchSubAgentStart"
    ResearchSubAgentComplete = "ResearchSubAgentComplete"
    ResearchVerificationStart = "ResearchVerificationStart"
    ResearchReportGenerated = "ResearchReportGenerated"
    ResearchToolRegistered = "ResearchToolRegistered"
    ResearchTaskSpawned = "ResearchTaskSpawned"
    ResearchEvidenceFound = "ResearchEvidenceFound"
    ResearchCitationAdded = "ResearchCitationAdded"
    ResearchVerificationComplete = "ResearchVerificationComplete"
    ResearchConflictDetected = "ResearchConflictDetected"


class HookHandlerType(str, Enum):
    COMMAND = "command"
    PROMPT = "prompt"
    AGENT = "agent"


class HookHandler(BaseModel):
    """Hook handler definition (compatible subset)."""

    model_config = ConfigDict(extra="ignore")

    type: HookHandlerType

    # command type
    command: str | None = None
    timeout: int | None = None

    # prompt type
    prompt: str | None = None

    # agent type (verifier/agent hook)
    agent: dict[str, Any] | None = None


class HookMatcherGroup(BaseModel):
    """A matcher group in hooks configuration."""

    matcher: str = ""
    hooks: list[HookHandler] = Field(default_factory=list)


class LoadedPlugin(BaseModel):
    """An in-memory representation of a loaded plugin."""

    model_config = ConfigDict(extra="ignore")

    name: str
    root: Path
    manifest: PluginManifest

    skills: list[PluginSkill] = Field(default_factory=list)
    # Hook event -> matcher groups
    hooks: dict[HookEvent, list[HookMatcherGroup]] = Field(default_factory=dict)

    # Bundled servers / tooling provided by plugin
    mcp_servers: dict[str, MCPServer] = Field(default_factory=dict)
    lsp_servers: dict[str, LSPConfig] = Field(default_factory=dict)

    # Reserved for later Phases: plugin-supplied subagents.
    agents: list[dict[str, Any]] = Field(default_factory=list)

    enabled: bool = True


class HookDecision(BaseModel):
    """Decision object produced by hook handler outputs.

    Claude Code returns JSON with custom fields, but for our first integration
    we only model the most important fields we may act on.
    """

    model_config = ConfigDict(extra="allow")

    # For permission-like flows, hook may set decision to deny/allow.
    permissionDecision: Literal["allow", "deny", ""] | str | None = None
    permissionDecisionReason: str | None = None

    # Some hooks return opaque output under `hookSpecificOutput`.
    hookSpecificOutput: dict[str, Any] | None = None
