"""Load subagent definitions from `.claude/agents/` (project + user) and built-ins."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..storage_paths import iter_read_candidates

logger = logging.getLogger(__name__)

_AGENT_DEFS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_AGENT_DEFS_TTL: float = 30.0

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split markdown into (frontmatter dict, body). Mirrors plugin/skills strategy."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw_yaml = m.group(1)
    body = m.group(2)

    try:
        import yaml

        fm = yaml.safe_load(raw_yaml)
        if isinstance(fm, dict):
            return fm, body
    except Exception:
        pass

    fm: dict[str, Any] = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.lower() in ("true", "yes"):
            fm[key] = True
        elif value.lower() in ("false", "no"):
            fm[key] = False
        else:
            fm[key] = value
    return fm, body


@dataclass
class AgentDefinition:
    """One subagent (Claude Code frontmatter + body prompt)."""

    name: str
    description: str = ""
    prompt: str = ""
    tools: list[str] | None = None  # Claude-style names; None = inherit all (minus delegate)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None  # inherit | sonnet | opus | haiku | full model id
    max_turns: int | None = None
    isolation: str | None = None  # e.g. worktree
    permission_mode: str | None = None
    background: bool = False
    mcp_servers: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    source: str = "builtin"


def _coerce_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[\s,]+", val) if x.strip()]
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return []


def _parse_agent_md(path: Path, source: str) -> AgentDefinition | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm, body = _parse_yaml_frontmatter(text)
    name = str(fm.get("name", path.stem)).strip()
    if not name:
        return None
    desc = str(fm.get("description", "")).strip()
    tools_raw = fm.get("tools")
    tools: list[str] | None
    if tools_raw is None:
        tools = None
    else:
        tools = _coerce_str_list(tools_raw)
    disallowed = _coerce_str_list(fm.get("disallowedTools") or fm.get("disallowed_tools"))
    model = fm.get("model")
    model_s = str(model).strip() if model is not None else None
    if model_s == "":
        model_s = None
    max_turns = fm.get("maxTurns") or fm.get("max_turns")
    max_i: int | None = None
    if isinstance(max_turns, int):
        max_i = max_turns
    elif isinstance(max_turns, str) and max_turns.isdigit():
        max_i = int(max_turns)
    iso = fm.get("isolation")
    iso_s = str(iso).strip() if iso is not None else None
    if iso_s == "":
        iso_s = None
    permission_mode = fm.get("permissionMode") or fm.get("permission_mode")
    permission_mode_s = str(permission_mode).strip() if permission_mode is not None else None
    if permission_mode_s == "":
        permission_mode_s = None
    background_raw = fm.get("background", False)
    background = bool(background_raw) if isinstance(background_raw, bool) else str(background_raw).strip().lower() in {"1", "true", "yes", "on"}
    mcp_servers = _coerce_str_list(fm.get("mcpServers") or fm.get("mcp_servers"))
    hooks = _coerce_str_list(fm.get("hooks"))
    known_keys = {
        "name", "description", "tools", "disallowedTools", "disallowed_tools",
        "model", "maxTurns", "max_turns", "isolation", "permissionMode",
        "permission_mode", "background", "mcpServers", "mcp_servers", "hooks",
    }
    extra = {k: v for k, v in fm.items() if k not in known_keys}
    prompt_body = body.strip()
    return AgentDefinition(
        name=name,
        description=desc,
        prompt=prompt_body,
        tools=tools,
        disallowed_tools=disallowed,
        model=model_s,
        max_turns=max_i,
        isolation=iso_s,
        permission_mode=permission_mode_s,
        background=background,
        mcp_servers=mcp_servers,
        hooks=hooks,
        extra=extra,
        source=source,
    )


def _load_directory(agent_dir: Path, source: str) -> dict[str, AgentDefinition]:
    out: dict[str, AgentDefinition] = {}
    if not agent_dir.is_dir():
        return out
    for p in sorted(agent_dir.glob("*.md")):
        dfn = _parse_agent_md(p, source)
        if dfn:
            out[dfn.name] = dfn
        else:
            logger.debug("Skip unreadable agent file: %s", p)
    return out


def builtin_agent_definitions() -> dict[str, AgentDefinition]:
    """Built-in agents aligned with Claude Code naming (prompts are minimal; tools resolved elsewhere)."""
    defs = {
        "explore": AgentDefinition(
            name="explore",
            description="Fast read-only codebase exploration and search.",
            prompt=(
                "You are the Explore subagent: search and analyze the codebase read-only. "
                "Summarize findings clearly for the parent agent."
            ),
            tools=["Read", "Glob", "Grep", "Bash", "ls", "diagnostics"],
            source="builtin",
        ),
        "plan": AgentDefinition(
            name="plan",
            description="Research the codebase to gather context for planning (read-only).",
            prompt=(
                "You are the Plan subagent: read-only research to support planning. "
                "Do not modify files. Return structured context and file references."
            ),
            tools=["Read", "Glob", "Grep", "Bash", "ls", "diagnostics"],
            source="builtin",
        ),
        "general-purpose": AgentDefinition(
            name="general-purpose",
            description="General capable subagent for multi-step tasks including edits when needed.",
            prompt=(
                "You are a general-purpose subagent. Complete the assigned task thoroughly. "
                "Use tools as needed; prefer minimal, focused changes."
            ),
            tools=None,
            source="builtin",
        ),
        "code-review": AgentDefinition(
            name="code-review",
            description="Code review for quality, security, and maintainability.",
            prompt=(
                "You are a senior code reviewer. Be constructive and specific. "
                "Focus on correctness, security, performance, and clarity."
            ),
            tools=["Read", "Glob", "Grep", "diagnostics"],
            source="builtin",
        ),
    }
    clawteam_roles: dict[str, tuple[str, list[str]]] = {
        "clawteam-product-manager": (
            "Product strategy, scope and acceptance criteria.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-business-analyst": (
            "Business requirement analysis and process mapping.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-system-architect": (
            "System architecture, interfaces and trade-offs.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-ui-ux-designer": (
            "UX flows, interaction design and usability.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-dev-manager": (
            "Engineering execution planning and delivery management.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-team-lead": (
            "Cross-role technical coordination and decision alignment.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-rnd-backend": (
            "Backend engineering implementation.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-rnd-frontend": (
            "Frontend engineering implementation.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-rnd-mobile": (
            "Mobile engineering implementation and platform concerns.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-devops": (
            "CI/CD, release automation and deployment design.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-qa": (
            "Test strategy, coverage and quality validation.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-sre": (
            "Reliability engineering, observability and incident readiness.",
            ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-project-manager": (
            "Project scheduling, tracking, and cross-function governance.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "clawteam-scrum-master": (
            "Scrum facilitation and agile process optimization.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
    }
    for role, (desc, tools) in clawteam_roles.items():
        defs[role] = AgentDefinition(
            name=role,
            description=desc,
            prompt=f"You are the {role} role in clawteam. Execute role tasks and report concrete outputs.",
            tools=tools,
            source="builtin",
        )
    designteam_roles: dict[str, tuple[str, list[str]]] = {
        "designteam-user-researcher": (
            "User research framing, evidence, personas, and journey inputs.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "designteam-interaction-designer": (
            "Flows, IA, states, and interaction specifications.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "designteam-ui-designer": (
            "UI structure, patterns, components, and visual hierarchy.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "designteam-product-designer": (
            "Problem frame, outcomes, scope, and UX prioritization.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "designteam-visual-ops-designer": (
            "Brand-aligned visuals and growth or marketing surfaces.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
        "designteam-experience-design-expert": (
            "Experience principles, review, accessibility posture, and risk synthesis.",
            ["Read", "Glob", "Grep", "Bash", "diagnostics"],
        ),
    }
    for role, (desc, tools) in designteam_roles.items():
        defs[role] = AgentDefinition(
            name=role,
            description=desc,
            prompt=f"You are the {role} role in designteam. Execute role tasks and report concrete outputs.",
            tools=tools,
            source="builtin",
        )
    return defs


def load_merged_agent_definitions(working_directory: str) -> dict[str, AgentDefinition]:
    """Merge builtins <- user ~/.claude/agents <- project .claw/.clawcode/.claude agents (later wins).

    Results are cached with a 30-second TTL to avoid redundant disk I/O.
    """
    cache_key = working_directory
    now = time.monotonic()
    cached = _AGENT_DEFS_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < _AGENT_DEFS_TTL:
        return dict(cached[1])

    merged = dict(builtin_agent_definitions())
    home_agents = Path.home() / ".claude" / "agents"
    for name, dfn in _load_directory(home_agents, "user").items():
        merged[name] = dfn
    proj_candidates = list(iter_read_candidates(working_directory, Path("agents")))
    for proj_agents in reversed(proj_candidates):
        for name, dfn in _load_directory(proj_agents, "project").items():
            merged[name] = dfn
    _AGENT_DEFS_CACHE[cache_key] = (now, merged)
    return dict(merged)
