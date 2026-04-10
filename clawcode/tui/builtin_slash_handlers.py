"""Async handlers for built-in slash commands (invoked from ChatScreen)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import time
import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.settings import (
    Settings,
    append_context_path_to_clawcode_json,
    save_ui_style_mode_to_clawcode_json,
)
from ..message.service import MessageRole

if TYPE_CHECKING:
    from ..message.service import MessageService
    from ..plugin.manager import PluginManager
from ..integrations.git_workspace import (
    git_diff_stat,
    git_rev_parse_short,
    git_stash_push_message,
    git_status_porcelain_summary,
    git_tracked_paths_differing_from_head,
    is_git_repo,
)
from ..integrations.github_pr import (
    fetch_pr_comments,
    fetch_pr_review_context,
    format_pr_comments_markdown,
    github_auth_instructions,
    resolve_pr_ref,
    run_git_diff,
)
from ..llm.plan_store import PlanStore
from ..claw_learning.ops_observability import emit_ops_event, resolve_domain
from .checkpoint_workspace import (
    append_checkpoint_line,
    clear_keep_last_n,
    format_list_text,
    format_log_line,
    format_verify_report,
    validate_checkpoint_name,
    checkpoint_log_path,
)
from .multi_plan_routing import (
    MultiPlanRoutingArgs,
    build_routing_plan,
)
from .multi_backend_workflow import (
    build_backend_routing_meta,
    build_multi_backend_prompt,
)
from .multi_frontend_workflow import (
    build_frontend_routing_meta,
    build_multi_frontend_prompt,
)
from .multi_workflow import (
    build_fullstack_routing_meta,
    build_multi_workflow_prompt,
)
from .orchestrate_workflow import (
    build_orchestrate_prompt,
    parse_orchestrate_args,
)
from .clawteam_deeploop_pending import clawteam_deeploop_clear_pending, clawteam_deeploop_get_pending
from .multi_execute_workflow import (
    MultiExecuteArgs,
    build_execute_context,
    build_execute_prompt,
    build_model_assignment,
)
from ..learning.service import LearningService
from ..learning.params import (
    parse_evolve_args,
    parse_export_args,
    parse_import_args,
    parse_status_args,
)
from ..learning.experience_params import (
    parse_experience_apply_args,
    parse_experience_create_args,
    parse_experience_export_args,
    parse_experience_feedback_args,
    parse_experience_import_args,
    parse_experience_status_args,
)
from ..learning.team_experience_params import (
    parse_team_experience_apply_args,
    parse_team_experience_create_args,
    parse_team_experience_export_args,
    parse_team_experience_feedback_args,
    parse_team_experience_import_args,
    parse_team_experience_status_args,
)
from ..session import SessionService
from .architect_params import ArchitectArgs, parse_architect_args
from .builtin_slash import BuiltinSlashContext, BuiltinSlashOutcome
from .components.dialogs.display_mode import MODES as _DISPLAY_MODE_ITEMS
from .ui_style import (
    choose_secondary_ui_style_candidate,
    evaluate_ui_style_text,
    format_ui_style_compact,
    load_ui_anti_patterns,
    load_ui_anti_pattern_rules,
    load_ui_catalog,
    ui_catalog_candidate_hints,
)

_EXPORT_MSG_MAX = 12_000
_EXPORT_TOTAL_MAX = 400_000
_EXPORT_LIST_LIMIT = 10_000


def _clone_parts_for_fork(parts: list[Any]) -> list[Any]:
    from ..message.service import ContentPart

    out: list[Any] = []
    for p in parts:
        try:
            out.append(ContentPart.from_dict(p.to_dict()))
        except Exception:
            continue
    return out


def _export_message_markdown(msg: Any, max_chars: int = _EXPORT_MSG_MAX) -> str:
    from ..message.service import (
        ImageContent,
        ToolCallContent,
        ToolResultContent,
    )

    role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
    lines = [f"## {role}\n"]
    chunks: list[str] = []
    text = (getattr(msg, "content", None) or "").strip()
    if text:
        chunks.append(text[:max_chars] + ("…" if len(text) > max_chars else ""))
    thinking = (getattr(msg, "thinking", None) or "").strip()
    if thinking:
        cap = 2000
        chunks.append(
            f"_(thinking)_ {thinking[:cap]}{'…' if len(thinking) > cap else ''}"
        )
    for p in getattr(msg, "parts", None) or []:
        if isinstance(p, ToolCallContent):
            inj = p.input if isinstance(p.input, str) else str(p.input)
            chunks.append(f"- **tool** `{p.name}` {inj[:400]}{'…' if len(inj) > 400 else ''}")
        elif isinstance(p, ToolResultContent):
            c = p.content or ""
            cap2 = 2000
            chunks.append(
                f"- **tool result** ({p.tool_call_id}): {c[:cap2]}"
                f"{'…' if len(c) > cap2 else ''}"
            )
        elif isinstance(p, ImageContent):
            chunks.append("- _(image attachment omitted from export)_")
    if not chunks:
        chunks.append("_(no text body)_")
    lines.append("\n\n".join(chunks) + "\n")
    return "".join(lines)


def _message_text_body(msg: Any) -> str:
    chunks: list[str] = []
    txt = str(getattr(msg, "content", "") or "").strip()
    if txt:
        chunks.append(txt)
    for p in getattr(msg, "parts", None) or []:
        c = str(getattr(p, "content", "") or "").strip()
        if c:
            chunks.append(c)
    return "\n".join(chunks).strip()


def _context_ascii_bar(percent: int, width: int = 10) -> str:
    pct = min(100, max(0, int(percent)))
    filled = min(width, max(0, round(width * pct / 100)))
    return "█" * filled + "░" * (width - filled)


def _format_duration(seconds: int) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m, s2 = divmod(s, 60)
    if m < 60:
        return f"{m}m {s2}s"
    h, m2 = divmod(m, 60)
    return f"{h}h {m2}m {s2}s"


_CLAWCODE_TEMPLATE = """# CLAWCODE.md

Brief project context for clawcode (fill in with codebase details).

## Overview

## Repository layout

## Build & test

## Conventions

"""


def _release_notes_markdown() -> str:
    """Best-effort release notes from package metadata and README."""
    pkg_root = Path(__file__).resolve().parents[2]
    lines: list[str] = ["# Release notes (clawcode)\n\n"]
    ver: str | None = None
    p_toml = pkg_root.parent / "pyproject.toml"
    if p_toml.is_file():
        try:
            data = tomllib.loads(p_toml.read_text(encoding="utf-8"))
            proj = data.get("project")
            if isinstance(proj, dict):
                v = proj.get("version")
                if isinstance(v, str):
                    ver = v
        except OSError:
            pass
    if ver is None:
        with contextlib.suppress(importlib_metadata.PackageNotFoundError):
            ver = importlib_metadata.version("clawcode")
    lines.append(f"**Version:** {ver or 'unknown'}\n\n")
    readme = pkg_root.parent / "README.md"
    if readme.is_file():
        try:
            body = readme.read_text(encoding="utf-8")
        except OSError:
            body = ""
        if body.strip():
            lines.append("## README\n\n")
            cap = 12000
            lines.append(body[:cap])
            if len(body) > cap:
                lines.append("\n\n_(truncated)_\n")
            return "".join(lines)
    lines.append("No README.md found next to this installation.\n")
    return "".join(lines)


_REWIND_HELP = """# Rewind (clawcode)

## Conversation (database — soft-archive)

Messages are **not** deleted; they get `deleted_at` and disappear from the chat UI.

- `/rewind chat last` — archive everything **after** the last **user** message in this session.
- `/rewind chat <message_id>` — archive everything **after** that message (it must be active / not already archived).

## Git workspace (tracked files only)

- `/rewind git` — read-only: `git status` (porcelain) and `git diff --stat HEAD`.
- `/rewind git restore` — confirm, then restore **tracked** paths to **HEAD** (staged + worktree). **Untracked files are never removed.**

For file history inside a session without git, a future build may use DB `FileChange` rows once writes are recorded.
"""

_CHECKPOINT_HELP = """# Checkpoint (clawcode)

Record **git HEAD** snapshots under `.clawcode/checkpoints.log` and compare later with `verify`.

## Commands

- `/checkpoint create <name>` — append a line with current `git rev-parse --short HEAD`.
- `/checkpoint create <name> --stash` — run `git stash push` first (on failure nothing is logged); then append.
- `/checkpoint verify <name>` — diff from the **latest** log entry with that name to `HEAD` (`--stat` + `--name-status`).
- `/checkpoint list` — show all entries.
- `/checkpoint clear` — keep only the **last 5** entries.

Requires a **git** work tree. Before risky work, run tests or `/doctor` if you want a clean baseline; this command does not run your test suite.
"""


def _parse_checkpoint_create_args(parts: list[str]) -> tuple[str | None, bool, str | None]:
    """parts are tokens after `create`. Returns (name, do_stash, error_message)."""
    if not parts:
        return None, False, "Usage: `/checkpoint create <name>` or `/checkpoint create <name> --stash`"
    do_stash = len(parts) >= 1 and parts[-1] == "--stash"
    name_parts = parts[:-1] if do_stash else parts
    if not name_parts:
        return None, False, "Usage: `/checkpoint create <name>` or `/checkpoint create <name> --stash`"
    name = " ".join(name_parts).strip()
    verr = validate_checkpoint_name(name)
    if verr:
        return None, False, verr
    return name, do_stash, None


_CLAWTEAM_AGENT_CAPABILITIES: dict[str, str] = {
    "clawteam-product-manager": "Define product scope, goals, priorities, and acceptance criteria.",
    "clawteam-business-analyst": "Translate business needs into constraints, workflows, and requirement details.",
    "clawteam-system-architect": "Design technical architecture, interfaces, trade-offs, and risk controls.",
    "clawteam-ui-ux-designer": "Design user journeys, interaction flows, and interface proposals.",
    "clawteam-dev-manager": "Plan engineering execution, staffing, milestones, and delivery sequencing.",
    "clawteam-team-lead": "Coordinate cross-role execution, resolve blockers, and keep technical direction aligned.",
    "clawteam-rnd-backend": "Implement backend services, APIs, data models, and reliability-focused logic.",
    "clawteam-rnd-frontend": "Implement frontend UI, state flows, and client-side integrations.",
    "clawteam-rnd-mobile": "Implement mobile application features and platform-specific integration concerns.",
    "clawteam-devops": "Handle CI/CD pipelines, build/release automation, and deployment architecture.",
    "clawteam-qa": "Define test strategy, test cases, verification gates, and quality risk analysis.",
    "clawteam-sre": "Design observability, resilience, incident readiness, and operational reliability controls.",
    "clawteam-project-manager": "Track scope/schedule/resources and delivery status with execution governance.",
    "clawteam-scrum-master": "Facilitate agile ceremonies, flow efficiency, and team process improvements.",
}

_CLAWTEAM_AGENT_ALIASES: dict[str, str] = {
    "product-manager": "clawteam-product-manager",
    "business-analyst": "clawteam-business-analyst",
    "system-architect": "clawteam-system-architect",
    "ui-ux-designer": "clawteam-ui-ux-designer",
    "dev-manager": "clawteam-dev-manager",
    "team-lead": "clawteam-team-lead",
    "rnd-backend": "clawteam-rnd-backend",
    "rnd-frontend": "clawteam-rnd-frontend",
    "rnd-mobile": "clawteam-rnd-mobile",
    "devops": "clawteam-devops",
    "qa": "clawteam-qa",
    "sre": "clawteam-sre",
    "project-manager": "clawteam-project-manager",
    "scrum-master": "clawteam-scrum-master",
}

_CLAWTEAM_USAGE = (
    "Usage:\n"
    "- `/clawteam <requirement>`: auto-select and orchestrate multiple roles.\n"
    "- `/clawteam:<agent> <requirement>`: run one role only.\n"
    "- `/clawteam --agent <agent> <requirement>`: explicit single-role mode.\n\n"
    "- `/clawteam --deep_loop <requirement>`: run iterative deep loop workflow.\n"
    "- `/clawteam --deep_loop --max_iters <n> <requirement>`: deep loop with custom iteration cap.\n\n"
    "Available agents: "
    + ", ".join(f"`{k}`" for k in sorted(_CLAWTEAM_AGENT_CAPABILITIES))
)


def _parse_clawteam_args(tail: str) -> tuple[str | None, str, bool, int, str]:
    """Return (selected_agent, request, deep_loop, max_iters, error)."""
    raw = (tail or "").strip()
    default_max_iters = 100
    if not raw:
        return None, "", False, default_max_iters, _CLAWTEAM_USAGE
    try:
        tokens = shlex.split(raw)
    except ValueError as e:
        return None, "", False, default_max_iters, f"Invalid `/clawteam` arguments: {e}\n\n{_CLAWTEAM_USAGE}"

    selected_agent: str | None = None
    deep_loop = False
    max_iters = 100
    req_tokens: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--agent":
            if i + 1 >= len(tokens):
                return None, "", False, 5, f"`--agent` requires a value.\n\n{_CLAWTEAM_USAGE}"
            selected_agent = tokens[i + 1].strip().lower()
            i += 2
            continue
        if tok == "--deep_loop":
            deep_loop = True
            i += 1
            continue
        if tok == "--max_iters":
            if i + 1 >= len(tokens):
                return (
                    None,
                    "",
                    False,
                    default_max_iters,
                    f"`--max_iters` requires an integer value.\n\n{_CLAWTEAM_USAGE}",
                )
            raw_iters = tokens[i + 1].strip()
            try:
                max_iters = int(raw_iters)
            except ValueError:
                return (
                    None,
                    "",
                    False,
                    default_max_iters,
                    f"`--max_iters` must be an integer (got `{raw_iters}`).\n\n{_CLAWTEAM_USAGE}",
                )
            if max_iters < 1:
                return (
                    None,
                    "",
                    False,
                    default_max_iters,
                    f"`--max_iters` must be >= 1 (got `{max_iters}`).\n\n{_CLAWTEAM_USAGE}",
                )
            i += 2
            continue
        req_tokens.append(tok)
        i += 1

    req = " ".join(req_tokens).strip()
    if selected_agent and selected_agent not in _CLAWTEAM_AGENT_CAPABILITIES:
        selected_agent = _CLAWTEAM_AGENT_ALIASES.get(selected_agent, selected_agent)
    if selected_agent and selected_agent not in _CLAWTEAM_AGENT_CAPABILITIES:
        return (
            None,
            "",
            False,
            default_max_iters,
            f"Unknown `/clawteam` agent `{selected_agent}`.\n\n{_CLAWTEAM_USAGE}",
        )
    if not req:
        return None, "", False, default_max_iters, _CLAWTEAM_USAGE
    return selected_agent, req, deep_loop, max_iters, ""


def _build_clawteam_prompt(
    user_request: str,
    selected_agent: str | None,
    *,
    deep_loop: bool = False,
    max_iters: int = 100,
    tecap_context: list[dict[str, object]] | None = None,
    role_ecap_context: dict[str, dict[str, object]] | None = None,
    deeploop_thresholds: dict[str, object] | None = None,
) -> str:
    req = (user_request or "").strip() or "(no requirement text provided)"
    roster_lines = [
        f"- `{name}`: {desc}" for name, desc in sorted(_CLAWTEAM_AGENT_CAPABILITIES.items())
    ]
    roster_block = "\n".join(roster_lines)
    if selected_agent:
        mode_block = (
            "Execution mode: SINGLE-ROLE.\n"
            f"Use only this role unless a hard blocker requires escalation: `{selected_agent}`.\n"
        )
    else:
        mode_block = (
            "Execution mode: AUTO-ORCHESTRATION.\n"
            "Select a minimal but sufficient set of roles from the roster.\n"
            "Compose an adaptive workflow with serial and parallel stages when beneficial.\n"
        )
    if deep_loop:
        thresholds = deeploop_thresholds or {}
        min_gap_delta = float(thresholds.get("min_gap_delta", 0.05) or 0.05)
        rounds = int(thresholds.get("convergence_rounds", 2) or 2)
        handoff_target = float(thresholds.get("handoff_target", 0.85) or 0.85)
        deep_loop_block = (
            "Deep loop mode: ENABLED (`--deep_loop`).\n"
            f"Iteration cap: {max_iters} (`--max_iters`).\n"
            f"Convergence threshold (gap delta): {min_gap_delta}.\n"
            f"Convergence rounds: {rounds}.\n"
            f"Handoff target: {handoff_target}.\n\n"
            "Run an OUTER deep loop over clawteam collaboration until convergence or max iterations.\n"
            "For each iteration i, execute these four steps in order (each step must still follow the "
            "same clawteam orchestration protocol and role roster):\n"
            "1) 检查:\n"
            "   - Inspect previous integrated outcome and implementation status.\n"
            "   - Identify defects, risks, missing requirements, and quality gaps.\n"
            "   - Resolve prioritized issues and produce an updated integrated outcome.\n"
            "2) 深化设计:\n"
            "   - Deepen architecture, interfaces, constraints, and trade-off decisions.\n"
            "   - Refine design rationale and implementation-ready decisions.\n"
            "3) 扩展实现:\n"
            "   - Expand feature scope and implementation depth based on current outcome.\n"
            "   - Strengthen test coverage, reliability, and docs where applicable.\n"
            "4) 最终收敛:\n"
            "   - Run a dedicated evaluation pass comparing current vs previous iteration outcome.\n"
            "   - Compute/estimate `delta_score` in [0, 1] and set `converged`.\n"
            "   - If `delta_score <= 0.15` and there is no critical unresolved risk, stop loop.\n"
            "   - Otherwise continue to next iteration.\n\n"
            "Deep loop output contract (required every iteration):\n"
            "- Iteration index\n"
            "- iteration_goal\n"
            "- role_handoff_result\n"
            "- gap_before\n"
            "- gap_after\n"
            "- gap_delta\n"
            "- deviation_reason\n"
            "- Step outputs for the 4 steps above\n"
            "- IntegratedFinalOutcome (structured, reusable for next iteration)\n"
            "- Convergence report JSON-like block with keys:\n"
            "  - `delta_score`\n"
            "  - `converged`\n"
            "  - `reasons`\n"
            "  - `critical_risks`\n"
            "- Final line MUST be exactly one machine-readable line prefixed with `DEEP_LOOP_EVAL_JSON:`\n"
            "  Example:\n"
            '  DEEP_LOOP_EVAL_JSON: {"delta_score": 0.08, "converged": true, "reasons": "stabilized", "critical_risks": []}\n'
            "- Finalization line SHOULD be provided to support automatic writeback:\n"
            '  DEEP_LOOP_WRITEBACK_JSON: {"iteration": 1, "iteration_goal": "close gaps", "role_handoff_result": "ok", "gap_before": 0.3, "gap_after": 0.1, "deviation_reason": "", "handoff_success_rate": 0.9, "observed_score": 0.85, "result": "success"}\n'
            "After loop ends, provide one final mature high-level product version summary.\n\n"
        )
    else:
        deep_loop_block = ""
    tecap_lines: list[str] = []
    for row in list(tecap_context or [])[:3]:
        if not isinstance(row, dict):
            continue
        tecap_lines.append(
            f"- tecap_id=`{row.get('tecap_id','')}` score=`{row.get('score',0.0)}` "
            f"confidence=`{row.get('confidence',0.0)}` role_coverage=`{row.get('role_coverage',0.0)}`"
        )
    tecap_block = "\n".join(tecap_lines) if tecap_lines else "- (no matched TECAP)"
    role_lines: list[str] = []
    for role, row in sorted((role_ecap_context or {}).items()):
        if not isinstance(row, dict):
            continue
        role_lines.append(
            f"- {role}: ecap_id=`{row.get('ecap_id','')}` score=`{row.get('experience_score',0.0)}` "
            f"confidence=`{row.get('confidence',0.0)}` skill=`{row.get('skill_ref','')}`"
        )
    role_block = "\n".join(role_lines) if role_lines else "- (no role ECAP context)"
    return (
        "You are running clawcode built-in `/clawteam` as the primary orchestrator agent.\n"
        "You can autonomously call tools and delegate role tasks using the `Agent`/`Task` tool.\n\n"
        "Primary objective:\n"
        "Deliver the user's requested outcome through role-based collaboration.\n\n"
        f"{mode_block}\n"
        f"{deep_loop_block}"
        "TECAP context (retrieved):\n"
        f"{tecap_block}\n\n"
        "Role ECAP context (retrieved):\n"
        f"{role_block}\n\n"
        "Role roster (agent id -> capability):\n"
        f"{roster_block}\n\n"
        "Mandatory orchestration protocol:\n"
        "1) Analyze requirement and identify key workstreams.\n"
        "2) Choose roles strictly from the roster and explain why each role is needed.\n"
        "3) Build execution flow with explicit stages:\n"
        "   - which stages are parallel\n"
        "   - which stages are serial and dependency-gated\n"
        "4) Dispatch role tasks via `Agent` or `Task` using `agent=<role-id>`.\n"
        "5) Integrate outputs, resolve conflicts, and produce final consolidated deliverable.\n"
        "6) Include risks, assumptions, and recommended next actions.\n\n"
        "Output structure requirements:\n"
        "- Role selection\n"
        "- Workflow plan (parallel/serial)\n"
        "- Role execution results\n"
        "- Integrated final outcome\n"
        "- Risks and next steps\n\n"
        f"User requirement:\n{req}\n"
    )


def _build_tdd_prompt(user_request: str) -> str:
    req = (user_request or "").strip()
    request_block = req if req else "(no additional text)"
    return (
        "You are running clawcode built-in `/tdd` in strict mode.\n"
        "Follow this exact lifecycle and do not skip steps: SCAFFOLD -> RED -> GREEN -> REFACTOR -> COVERAGE GATE.\n\n"
        "Hard rules:\n"
        "1) Test-first always: write/adjust tests before writing implementation.\n"
        "2) RED before GREEN: run tests and show expected failing results first.\n"
        "3) Smallest passing change only in GREEN.\n"
        "4) Re-run tests after every code change and after refactor.\n"
        "5) Coverage gate: target >= 80%; for security/auth/financial/core critical logic target 100%.\n"
        "6) Test behavior and user-visible outcomes, not internal implementation details.\n\n"
        "Phase requirements:\n"
        "- SCAFFOLD: define interfaces/types/function signatures and files to touch.\n"
        "- RED: add tests (happy path, edge cases, error paths) and run them; confirm expected failures.\n"
        "- GREEN: implement minimal code to pass current failing tests; run tests.\n"
        "- REFACTOR: improve structure/readability while keeping behavior; run tests again.\n"
        "- COVERAGE GATE: run coverage; if below threshold, add tests and loop RED->GREEN->REFACTOR.\n\n"
        "Output for each phase:\n"
        "- What changed (files + concise rationale)\n"
        "- Command(s) run\n"
        "- Key test/coverage results\n"
        "- Next step decision\n\n"
        f"User request:\n{request_block}\n"
    )


def _build_multi_plan_prompt(user_request: str) -> str:
    req = (user_request or "").strip()
    if not req:
        return (
            "Usage: `/multi-plan <requirement>`\n\n"
            "Example: `/multi-plan Design and implement tenant-aware rate limiting for API gateway`"
        )
    return (
        "You are running clawcode built-in `/multi-plan` (multi-model collaborative planning).\n"
        "This command is strictly PLAN-ONLY and must NOT perform production code modifications.\n\n"
        "Core protocol:\n"
        "1) Research phase:\n"
        "   - Retrieve complete context from the current workspace.\n"
        "   - Use semantic/code search and targeted file reads.\n"
        "   - Resolve ambiguity with clarifying questions before planning if needed.\n"
        "2) Analysis phase (parallel perspectives):\n"
        "   - Generate backend-focused analysis (architecture, correctness, performance, risks).\n"
        "   - Generate frontend/UX-focused analysis when relevant (interaction, accessibility, consistency).\n"
        "   - Treat the two perspectives as complementary and independent.\n"
        "3) Cross-validation phase:\n"
        "   - Identify consensus points.\n"
        "   - Identify divergences and trade-offs.\n"
        "   - Decide final direction with explicit rationale.\n"
        "4) Plan delivery phase:\n"
        "   - Produce a concrete implementation plan only.\n"
        "   - Do NOT execute edits, commands that mutate files, or commits.\n\n"
        "Execution constraints:\n"
        "- External/parallel analysts are advisory only and have zero filesystem write authority.\n"
        "- Stop-loss: do not move to the next phase until the current phase output is validated.\n"
        "- No implicit implementation. End with planning deliverable and execution handoff guidance.\n\n"
        "Output format (required):\n"
        "## Implementation Plan: <Task Name>\n"
        "## Task Type\n"
        "- Frontend / Backend / Fullstack (pick one with rationale)\n"
        "## Technical Solution\n"
        "## Implementation Steps\n"
        "1. ...\n"
        "## Key Files\n"
        "| File | Operation | Description |\n"
        "|------|-----------|-------------|\n"
        "## Risks and Mitigation\n"
        "| Risk | Mitigation |\n"
        "|------|------------|\n"
        "## Test Plan\n"
        "- Unit / integration / e2e scope\n\n"
        "Final handoff text (required):\n"
        "- State clearly that this is a plan-only response.\n"
        "- Ask user to approve or request plan adjustments before execution.\n\n"
        f"User requirement:\n{req}\n"
    )


def _parse_multi_plan_args(tail: str) -> tuple[MultiPlanRoutingArgs | None, str]:
    raw = (tail or "").strip()
    if raw.lower() in {"show", "list"}:
        return MultiPlanRoutingArgs(requirement=raw.lower()), ""
    if not raw:
        return MultiPlanRoutingArgs(requirement=""), ""
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return None, f"Invalid `/multi-plan` args: {e}"
    out = MultiPlanRoutingArgs()
    free: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode" and i + 1 < len(argv):
            m = argv[i + 1].strip().lower()
            if m not in {"auto", "manual", "hybrid"}:
                return None, "`--mode` must be one of: auto, manual, hybrid."
            out.mode = m  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--strategy" and i + 1 < len(argv):
            s = argv[i + 1].strip().lower()
            if s not in {"quality-first", "balanced", "speed-first", "cost-first"}:
                return None, "`--strategy` must be one of: quality-first, balanced, speed-first, cost-first."
            out.strategy = s  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--model-backend" and i + 1 < len(argv):
            out.model_backend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-frontend" and i + 1 < len(argv):
            out.model_frontend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-synthesis" and i + 1 < len(argv):
            out.model_synthesis = argv[i + 1]
            i += 2
            continue
        if tok == "--fallback" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, "`--fallback` must be `on` or `off`."
            out.fallback = v == "on"
            i += 2
            continue
        if tok == "--explain-routing":
            out.explain_routing = True
            i += 1
            continue
        if tok.startswith("--"):
            return None, (
                "Usage: `/multi-plan <requirement> [--mode auto|manual|hybrid] "
                "[--strategy quality-first|balanced|speed-first|cost-first] "
                "[--model-backend <id>] [--model-frontend <id>] [--model-synthesis <id>] "
                "[--fallback on|off] [--explain-routing]`"
            )
        free.append(tok)
        i += 1
    out.requirement = " ".join(free).strip()
    return out, ""


def _format_multi_plan_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("multi-plan", limit=limit)
    if not rows:
        return (
            "No `/multi-plan` artifacts found yet.\n\n"
            "Run `/multi-plan <requirement>` first to generate and persist plan versions."
        )
    lines = [
        "# multi-plan artifacts\n\n",
        "| Created | Session | Strategy | Models | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        strategy = str(meta.get("strategy") or "-")
        sel = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
        models = ", ".join(
            str((v or {}).get("model_id") or "")
            for _, v in sorted(sel.items())
            if isinstance(v, dict) and str(v.get("model_id") or "").strip()
        )
        models = models or "-"
        md = b.markdown_path or "-"
        js = b.json_path or "-"
        lines.append(f"| {created} | `{sid}` | `{strategy}` | `{models}` | `{md}` | `{js}` |\n")
    return "".join(lines)


def _parse_multi_execute_args(tail: str, *, root: Path) -> tuple[MultiExecuteArgs | None, str]:
    raw = (tail or "").strip()
    if raw.lower() in {"show", "list"}:
        return MultiExecuteArgs(request=raw.lower()), ""
    if not raw:
        return None, (
            "Usage: `/multi-execute <requirement> [--mode auto|manual|hybrid] "
            "[--strategy quality-first|balanced|speed-first|cost-first] [--fallback on|off] "
            "[--audit on|off] [--from-plan <path>] [--model-backend <id>] [--model-frontend <id>] "
            "[--model-synthesis <id>] [--explain-routing]`\n\n"
            "Example: `/multi-execute implement checkout retries --strategy quality-first --audit on`"
        )
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return None, f"Invalid `/multi-execute` args: {e}"
    out = MultiExecuteArgs()
    free: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"auto", "manual", "hybrid"}:
                return None, "`--mode` must be one of: auto, manual, hybrid."
            out.mode = v  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--strategy" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"quality-first", "balanced", "speed-first", "cost-first"}:
                return None, "`--strategy` must be one of: quality-first, balanced, speed-first, cost-first."
            out.strategy = v
            i += 2
            continue
        if tok == "--fallback" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, "`--fallback` must be `on` or `off`."
            out.fallback = v == "on"
            i += 2
            continue
        if tok == "--audit" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, "`--audit` must be `on` or `off`."
            out.audit = v  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--from-plan" and i + 1 < len(argv):
            p = argv[i + 1].strip()
            if not p:
                return None, "`--from-plan` requires a file path."
            out.from_plan = p
            i += 2
            continue
        if tok == "--model-backend" and i + 1 < len(argv):
            out.model_backend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-frontend" and i + 1 < len(argv):
            out.model_frontend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-synthesis" and i + 1 < len(argv):
            out.model_synthesis = argv[i + 1]
            i += 2
            continue
        if tok == "--explain-routing":
            out.explain_routing = True
            i += 1
            continue
        if tok.startswith("--"):
            return None, f"Unknown arg `{tok}` for `/multi-execute`."
        free.append(tok)
        i += 1
    out.request = " ".join(free).strip()
    if out.from_plan:
        p = Path(out.from_plan)
        if not p.is_absolute():
            p = (root / p).resolve()
        if not p.exists() or not p.is_file():
            return None, f"`--from-plan` file not found: {p}"
    if not out.request and not out.from_plan:
        return None, "Please provide requirement text or `--from-plan <path>`."
    if not out.from_plan and len(argv) == 1:
        p = Path(out.request)
        try_p = p if p.is_absolute() else (root / p).resolve()
        if try_p.exists() and try_p.is_file():
            out.from_plan = out.request
            out.request = ""
    return out, ""


def _parse_multi_backend_args(tail: str) -> tuple[MultiPlanRoutingArgs | None, bool | None, str]:
    """Returns (routing_args, audit_on, err). audit_on is None when show/list."""
    raw = (tail or "").strip()
    if raw.lower() in {"show", "list"}:
        return MultiPlanRoutingArgs(requirement=raw.lower()), None, ""
    if not raw:
        return (
            None,
            None,
            (
                "Usage: `/multi-backend <backend task> [--mode auto|manual|hybrid] "
                "[--strategy quality-first|balanced|speed-first|cost-first] [--fallback on|off] "
                "[--audit on|off] [--model-backend <id>] [--model-frontend <id>] "
                "[--model-synthesis <id>] [--explain-routing]`\n\n"
                "Example: `/multi-backend Add idempotent retry to payment API --strategy balanced`"
            ),
        )
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return None, None, f"Invalid `/multi-backend` args: {e}"
    out = MultiPlanRoutingArgs()
    audit_on = True
    free: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode" and i + 1 < len(argv):
            m = argv[i + 1].strip().lower()
            if m not in {"auto", "manual", "hybrid"}:
                return None, None, "`--mode` must be one of: auto, manual, hybrid."
            out.mode = m  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--strategy" and i + 1 < len(argv):
            s = argv[i + 1].strip().lower()
            if s not in {"quality-first", "balanced", "speed-first", "cost-first"}:
                return None, None, "`--strategy` must be one of: quality-first, balanced, speed-first, cost-first."
            out.strategy = s  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--fallback" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--fallback` must be `on` or `off`."
            out.fallback = v == "on"
            i += 2
            continue
        if tok == "--audit" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--audit` must be `on` or `off`."
            audit_on = v == "on"
            i += 2
            continue
        if tok == "--model-backend" and i + 1 < len(argv):
            out.model_backend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-frontend" and i + 1 < len(argv):
            out.model_frontend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-synthesis" and i + 1 < len(argv):
            out.model_synthesis = argv[i + 1]
            i += 2
            continue
        if tok == "--explain-routing":
            out.explain_routing = True
            i += 1
            continue
        if tok.startswith("--"):
            return None, None, f"Unknown arg `{tok}` for `/multi-backend`."
        free.append(tok)
        i += 1
    out.requirement = " ".join(free).strip()
    if not out.requirement:
        return None, None, "Please provide a backend task description."
    return out, audit_on, ""


def _parse_multi_frontend_args(tail: str) -> tuple[MultiPlanRoutingArgs | None, bool | None, str]:
    """Returns (routing_args, audit_on, err). audit_on is None when show/list."""
    raw = (tail or "").strip()
    if raw.lower() in {"show", "list"}:
        return MultiPlanRoutingArgs(requirement=raw.lower()), None, ""
    if not raw:
        return (
            None,
            None,
            (
                "Usage: `/multi-frontend <UI task> [--mode auto|manual|hybrid] "
                "[--strategy quality-first|balanced|speed-first|cost-first] [--fallback on|off] "
                "[--audit on|off] [--model-backend <id>] [--model-frontend <id>] "
                "[--model-synthesis <id>] [--explain-routing]`\n\n"
                "Example: `/multi-frontend Add responsive dashboard cards --strategy balanced`"
            ),
        )
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return None, None, f"Invalid `/multi-frontend` args: {e}"
    out = MultiPlanRoutingArgs()
    audit_on = True
    free: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode" and i + 1 < len(argv):
            m = argv[i + 1].strip().lower()
            if m not in {"auto", "manual", "hybrid"}:
                return None, None, "`--mode` must be one of: auto, manual, hybrid."
            out.mode = m  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--strategy" and i + 1 < len(argv):
            s = argv[i + 1].strip().lower()
            if s not in {"quality-first", "balanced", "speed-first", "cost-first"}:
                return None, None, "`--strategy` must be one of: quality-first, balanced, speed-first, cost-first."
            out.strategy = s  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--fallback" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--fallback` must be `on` or `off`."
            out.fallback = v == "on"
            i += 2
            continue
        if tok == "--audit" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--audit` must be `on` or `off`."
            audit_on = v == "on"
            i += 2
            continue
        if tok == "--model-backend" and i + 1 < len(argv):
            out.model_backend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-frontend" and i + 1 < len(argv):
            out.model_frontend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-synthesis" and i + 1 < len(argv):
            out.model_synthesis = argv[i + 1]
            i += 2
            continue
        if tok == "--explain-routing":
            out.explain_routing = True
            i += 1
            continue
        if tok.startswith("--"):
            return None, None, f"Unknown arg `{tok}` for `/multi-frontend`."
        free.append(tok)
        i += 1
    out.requirement = " ".join(free).strip()
    if not out.requirement:
        return None, None, "Please provide a UI or frontend task description."
    return out, audit_on, ""


def _parse_multi_workflow_args(tail: str) -> tuple[MultiPlanRoutingArgs | None, bool | None, str]:
    """Returns (routing_args, audit_on, err). audit_on is None when show/list."""
    raw = (tail or "").strip()
    if raw.lower() in {"show", "list"}:
        return MultiPlanRoutingArgs(requirement=raw.lower()), None, ""
    if not raw:
        return (
            None,
            None,
            (
                "Usage: `/multi-workflow <task> [--mode auto|manual|hybrid] "
                "[--strategy quality-first|balanced|speed-first|cost-first] [--fallback on|off] "
                "[--audit on|off] [--model-backend <id>] [--model-frontend <id>] "
                "[--model-synthesis <id>] [--explain-routing]`\n\n"
                "Example: `/multi-workflow Add checkout + payment UI --strategy balanced`"
            ),
        )
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return None, None, f"Invalid `/multi-workflow` args: {e}"
    out = MultiPlanRoutingArgs()
    audit_on = True
    free: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode" and i + 1 < len(argv):
            m = argv[i + 1].strip().lower()
            if m not in {"auto", "manual", "hybrid"}:
                return None, None, "`--mode` must be one of: auto, manual, hybrid."
            out.mode = m  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--strategy" and i + 1 < len(argv):
            s = argv[i + 1].strip().lower()
            if s not in {"quality-first", "balanced", "speed-first", "cost-first"}:
                return None, None, "`--strategy` must be one of: quality-first, balanced, speed-first, cost-first."
            out.strategy = s  # type: ignore[assignment]
            i += 2
            continue
        if tok == "--fallback" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--fallback` must be `on` or `off`."
            out.fallback = v == "on"
            i += 2
            continue
        if tok == "--audit" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            if v not in {"on", "off"}:
                return None, None, "`--audit` must be `on` or `off`."
            audit_on = v == "on"
            i += 2
            continue
        if tok == "--model-backend" and i + 1 < len(argv):
            out.model_backend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-frontend" and i + 1 < len(argv):
            out.model_frontend = argv[i + 1]
            i += 2
            continue
        if tok == "--model-synthesis" and i + 1 < len(argv):
            out.model_synthesis = argv[i + 1]
            i += 2
            continue
        if tok == "--explain-routing":
            out.explain_routing = True
            i += 1
            continue
        if tok.startswith("--"):
            return None, None, f"Unknown arg `{tok}` for `/multi-workflow`."
        free.append(tok)
        i += 1
    out.requirement = " ".join(free).strip()
    if not out.requirement:
        return None, None, "Please provide a full-stack or feature task description."
    return out, audit_on, ""


def _format_multi_backend_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("multi-backend", limit=limit)
    if not rows:
        return (
            "No `/multi-backend` artifacts found yet.\n\n"
            "Run `/multi-backend <backend task>` first."
        )
    lines = [
        "# multi-backend artifacts\n\n",
        "| Created | Session | Workflow | Strategy | Models | Audit | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        workflow = str(meta.get("workflow") or "backend")
        strategy = str(meta.get("strategy") or "-")
        sel = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
        models = ", ".join(
            str((v or {}).get("model_id") or "")
            for _, v in sorted(sel.items())
            if isinstance(v, dict) and str(v.get("model_id") or "").strip()
        )
        models = models or "-"
        be = meta.get("backend_meta") if isinstance(meta.get("backend_meta"), dict) else {}
        audit = str(be.get("audit") or "-")
        lines.append(
            f"| {created} | `{sid}` | `{workflow}` | `{strategy}` | `{models}` | `{audit}` | "
            f"`{b.markdown_path or '-'}` | `{b.json_path or '-'}` |\n"
        )
    return "".join(lines)


def _format_multi_frontend_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("multi-frontend", limit=limit)
    if not rows:
        return (
            "No `/multi-frontend` artifacts found yet.\n\n"
            "Run `/multi-frontend <UI task>` first."
        )
    lines = [
        "# multi-frontend artifacts\n\n",
        "| Created | Session | Workflow | Strategy | Models | Audit | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        workflow = str(meta.get("workflow") or "frontend")
        strategy = str(meta.get("strategy") or "-")
        sel = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
        models = ", ".join(
            str((v or {}).get("model_id") or "")
            for _, v in sorted(sel.items())
            if isinstance(v, dict) and str(v.get("model_id") or "").strip()
        )
        models = models or "-"
        fe = meta.get("frontend_meta") if isinstance(meta.get("frontend_meta"), dict) else {}
        audit = str(fe.get("audit") or "-")
        lines.append(
            f"| {created} | `{sid}` | `{workflow}` | `{strategy}` | `{models}` | `{audit}` | "
            f"`{b.markdown_path or '-'}` | `{b.json_path or '-'}` |\n"
        )
    return "".join(lines)


def _format_multi_workflow_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("multi-workflow", limit=limit)
    if not rows:
        return (
            "No `/multi-workflow` artifacts found yet.\n\n"
            "Run `/multi-workflow <task>` first."
        )
    lines = [
        "# multi-workflow artifacts\n\n",
        "| Created | Session | Workflow | Strategy | Models | Audit | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        workflow = str(meta.get("workflow") or "fullstack")
        strategy = str(meta.get("strategy") or "-")
        sel = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
        models = ", ".join(
            str((v or {}).get("model_id") or "")
            for _, v in sorted(sel.items())
            if isinstance(v, dict) and str(v.get("model_id") or "").strip()
        )
        models = models or "-"
        fs = meta.get("fullstack_meta") if isinstance(meta.get("fullstack_meta"), dict) else {}
        audit = str(fs.get("audit") or "-")
        lines.append(
            f"| {created} | `{sid}` | `{workflow}` | `{strategy}` | `{models}` | `{audit}` | "
            f"`{b.markdown_path or '-'}` | `{b.json_path or '-'}` |\n"
        )
    return "".join(lines)


def _format_orchestrate_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("orchestrate", limit=limit)
    if not rows:
        return (
            "No `/orchestrate` artifacts found yet.\n\n"
            "Run `/orchestrate feature \"…\"` or `/orchestrate custom …` first."
        )
    lines = [
        "# orchestrate artifacts\n\n",
        "| Created | Session | Type | Chain | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        otype = str(meta.get("orchestrate_type") or "-")
        chain = meta.get("orchestrate_chain")
        if isinstance(chain, list):
            chain_s = " → ".join(str(x) for x in chain)
        else:
            chain_s = str(chain or "-")
        lines.append(
            f"| {created} | `{sid}` | `{otype}` | `{chain_s}` | "
            f"`{b.markdown_path or '-'}` | `{b.json_path or '-'}` |\n"
        )
    return "".join(lines)


def _format_multi_execute_list(store: PlanStore, *, limit: int = 100) -> str:
    rows = store.list_bundles_in_subdir("multi-execute", limit=limit)
    if not rows:
        return (
            "No `/multi-execute` artifacts found yet.\n\n"
            "Run `/multi-execute <requirement>` or `/multi-execute --from-plan <path>` first."
        )
    lines = [
        "# multi-execute artifacts\n\n",
        "| Created | Session | Strategy | Models | Audit | Markdown | JSON |\n",
        "| --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    for b in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(b.created_at or 0)))
        sid = (b.session_id or "-").strip() or "-"
        meta = b.routing_meta if isinstance(getattr(b, "routing_meta", None), dict) else {}
        strategy = str(meta.get("strategy") or "-")
        sel = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
        models = ", ".join(
            str((v or {}).get("model_id") or "")
            for _, v in sorted(sel.items())
            if isinstance(v, dict) and str(v.get("model_id") or "").strip()
        )
        models = models or "-"
        exe = meta.get("execution_meta") if isinstance(meta.get("execution_meta"), dict) else {}
        audit = str(exe.get("audit") or "-")
        lines.append(
            f"| {created} | `{sid}` | `{strategy}` | `{models}` | `{audit}` | "
            f"`{b.markdown_path or '-'}` | `{b.json_path or '-'}` |\n"
        )
    return "".join(lines)


def _build_code_review_prompt(user_request: str) -> str:
    req = (user_request or "").strip()
    scope_hint = req if req else "Review all uncommitted changes in the current workspace."
    return (
        "You are running clawcode built-in `/code-review` for local workspace changes.\n"
        "Perform a practical code review with severity-ranked findings and a commit gate decision.\n\n"
        "Scope and context gathering:\n"
        "1) Inspect changed files with `git diff --name-only HEAD`.\n"
        "2) Read relevant diffs with `git diff -- <file>` (or scoped equivalent).\n"
        "3) If git is unavailable, explain limits and review best-effort local changes.\n\n"
        "Review categories:\n"
        "- CRITICAL (security): hardcoded secrets, injection risks, path traversal, auth/authz gaps, unsafe deserialization.\n"
        "- HIGH (quality): missing error handling, dangerous side effects, major correctness risks, unstable behavior.\n"
        "- MEDIUM (maintainability): complexity, unclear naming, TODO/FIXME debt, weak validation, missing docs/tests.\n"
        "- LOW (style/nits): minor consistency and readability improvements.\n\n"
        "Output requirements:\n"
        "1) Summary: overall risk + change scope.\n"
        "2) Findings: ordered by severity; include file, line/range, issue, impact, and concrete fix suggestion.\n"
        "3) Commit gate: `block_commit=true` if any CRITICAL/HIGH finding exists; otherwise `block_commit=false`.\n"
        "4) Quick remediation checklist.\n\n"
        "Constraints:\n"
        "- Focus on real defects and regressions; avoid speculative noise.\n"
        "- Do not claim checks you did not run.\n"
        "- Keep findings actionable and code-specific.\n\n"
        f"User review request:\n{scope_hint}\n"
    )


def _detect_output_language(user_request: str) -> str:
    text = (user_request or "").strip()
    if not text:
        return "English"
    cjk = 0
    ascii_alpha = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            cjk += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            ascii_alpha += 1
    if cjk > ascii_alpha:
        return "Chinese"
    return "English"


def _build_architect_prompt(args: ArchitectArgs) -> str:
    language = _detect_output_language(args.request)
    mode_hint = {
        "design": "design a target architecture",
        "review": "review and improve an existing architecture",
        "refactor": "propose an architecture-aware refactor plan",
    }.get(args.mode, "design a target architecture")

    scope_block = args.scope if args.scope else "(not explicitly constrained)"
    constraints_block = args.constraints if args.constraints else "(none provided)"
    fmt_block = (
        "Output JSON with keys: summary, current_state, requirements, design_proposal, "
        "tradeoffs, risks, next_steps."
        if args.as_json
        else "Output in concise markdown sections."
    )
    adr_block = (
        "\nADR section required:\n"
        "- Context\n- Decision\n- Consequences (positive/negative)\n- Alternatives considered\n"
        "- Status\n- Date\n"
        if args.include_adr
        else ""
    )
    checklist_block = (
        "\nSystem design checklist required:\n"
        "- Functional requirements coverage\n"
        "- Non-functional requirements (performance, security, scalability)\n"
        "- Technical design (components, data flow, integration, errors, testing)\n"
        "- Operations (deploy, monitor, backup/recovery, rollback)\n"
        if args.include_checklist
        else ""
    )
    return (
        "You are running clawcode built-in `/architect` (enhanced mode).\n"
        f"Primary task: {mode_hint}.\n"
        f"Respond in: {language}. Follow the user's language when possible.\n\n"
        "Use this architecture process exactly:\n"
        "1) Current State Analysis\n"
        "2) Requirements Gathering (functional + non-functional)\n"
        "3) Design Proposal (components, data flow, API/integration contracts)\n"
        "4) Trade-Off Analysis for key decisions using:\n"
        "   - Pros\n"
        "   - Cons\n"
        "   - Alternatives\n"
        "   - Decision and rationale\n\n"
        "Always include:\n"
        "- Architectural principles: modularity, scalability, maintainability, security, performance\n"
        "- Red flags/anti-pattern scan: Big Ball of Mud, Golden Hammer, Premature Optimization, "
        "Tight Coupling, God Object, Analysis Paralysis\n"
        f"- Output format rule: {fmt_block}\n"
        f"{adr_block}"
        f"{checklist_block}\n"
        "User request:\n"
        f"{args.request}\n\n"
        "Explicit scope:\n"
        f"{scope_block}\n\n"
        "Additional constraints:\n"
        f"{constraints_block}\n"
    )


async def handle_builtin_slash(
    head: str,
    tail: str,
    *,
    settings: Settings,
    session_service: SessionService | None,
    context: BuiltinSlashContext | None = None,
    plugin_manager: PluginManager | None = None,
    message_service: MessageService | None = None,
) -> BuiltinSlashOutcome:
    ctx = context or BuiltinSlashContext()
    alias_map = {
        "tecap-create": "team-experience-create",
        "tecap-status": "team-experience-status",
        "tecap-export": "team-experience-export",
        "tecap-import": "team-experience-import",
        "tecap-apply": "team-experience-apply",
        "tecap-feedback": "team-experience-feedback",
    }
    head = alias_map.get(head, head)
    wd = (settings.working_directory or ".").strip() or "."
    root = Path(wd).expanduser().resolve()
    _ui_cli_host = str(getattr(settings, "cli_launch_directory", "") or "").strip() or None

    if head == "todos":
        lines = ["# Current todos\n\n"]
        if not ctx.todos:
            lines.append(
                "No todo items in the HUD right now. "
                "Items from an active `/plan` build or agent todo tools will show here.\n"
            )
        else:
            for content, status in ctx.todos:
                lines.append(f"- **{status}** {content}\n")
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "upgrade":
        text = (
            "**clawcode** has no built-in “Max” subscription or vendor rate-limit tier.\n\n"
            "Configure your LLM provider API keys, base URLs, and models in `.clawcode.json` / "
            "environment variables (`CLAWCODE_*`). Higher quotas come from your chosen provider "
            "account, not from clawcode itself.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "usage":
        cw_line = (
            f"- **Context window (approx.):** {ctx.context_window_size:,} tokens\n"
            if ctx.context_window_size
            else "- **Context window (approx.):** (unknown for this model)\n"
        )
        lines = [
            "# Usage (HUD-aligned)\n\n",
            f"- **Model:** {ctx.model_label or '(unknown)'}\n",
            cw_line,
            f"- **Context fill (estimate):** {ctx.context_percent}%\n",
            f"- **Session tokens (DB):** prompt {ctx.session_prompt_tokens:,} · "
            f"completion {ctx.session_completion_tokens:,}\n",
            f"- **This turn (live):** input {ctx.turn_input_tokens:,} · "
            f"output {ctx.turn_output_tokens:,}\n\n",
            "The bottom HUD bar shows the same context bar during the session.\n",
        ]
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "vim":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="",
            ui_action="toggle_vim",
        )

    if head == "debug":
        text = (
            "**Debug (clawcode session)**\n\n"
            "There is no separate on-disk “session debug log” file in this build. "
            "Structured logs go to the process logger (console / JSON depending on CLI flags).\n\n"
            "Open the in-app log viewer with **Ctrl+L** (placeholder UI; full tail-of-file support "
            "may be added later).\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "init":
        claw = root / "CLAWCODE.md"
        if not claw.is_file():
            try:
                claw.write_text(_CLAWCODE_TEMPLATE, encoding="utf-8")
            except OSError as e:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not create CLAWCODE.md: {e}",
                )
            note = (
                f"Created template `{claw}`.\n\n"
            )
        else:
            note = f"`{claw}` already exists; the assistant will update or expand it as needed.\n\n"

        prompt = (
            f"{note}"
            "You are running the clawcode `/init` workflow.\n"
            "Explore the codebase under the project root and produce a thorough CLAWCODE.md "
            "(or update the existing file) with: project overview, directory map, build/test commands, "
            "coding conventions, and important integration points. Use file tools to read structure; "
            "write the final content to CLAWCODE.md at the project root.\n"
            f"Project root: {root}\n"
        )
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)

    if head == "insights":
        if session_service is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Session service is not available (database not initialized).",
            )
        sessions = await session_service.list(limit=40)
        lines: list[str] = ["# clawcode session insights\n"]
        if not sessions:
            lines.append("No sessions found.\n")
        else:
            lines.append("| Title | Messages | Prompt tok | Completion tok | Cost (USD) | Updated |\n")
            lines.append("| --- | ---: | ---: | ---: | ---: | --- |\n")
            for s in sessions:
                from datetime import UTC, datetime

                ts = datetime.fromtimestamp(s.updated_at, tz=UTC).strftime("%Y-%m-%d %H:%M") + " UTC"
                lines.append(
                    f"| {s.title[:60]} | {s.message_count} | {s.prompt_tokens} | "
                    f"{s.completion_tokens} | {s.cost:.4f} | {ts} |\n"
                )
        lines.append(
            "\nYou can ask follow-up questions in chat for deeper analysis of specific sessions.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "pr-comments":
        pr = resolve_pr_ref(tail, str(root))
        if pr is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "Usage: `/pr-comments <number>` or paste a GitHub pull request URL.\n"
                    "Repository is taken from `git remote get-url origin` when you pass a number only."
                ),
            )
        try:
            data = await fetch_pr_comments(pr)
            md = format_pr_comments_markdown(data)
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=md)
        except RuntimeError as e:
            if str(e) == "no_github_auth":
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=github_auth_instructions(),
                )
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"GitHub error: {e}",
            )
        except Exception as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"Failed to load PR comments: {e}",
            )

    if head == "review":
        pr = resolve_pr_ref(tail, str(root))
        if pr is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "Usage: `/review <number>` or paste a GitHub pull request URL.\n"
                    "Repository is taken from `git remote get-url origin` when you pass a number only."
                ),
            )
        try:
            ctx = await fetch_pr_review_context(pr)
            pull = ctx.get("pull") or {}
            title = pull.get("title", "")
            files = ctx.get("files_meta") or []
            patch = ctx.get("patch_excerpt") or ""
            file_summary = ", ".join(
                f"{f.get('filename', '')} ({f.get('status', '')})" for f in files[:30]
            )
            prompt = (
                "You are performing a pull request review for clawcode.\n"
                f"PR #{pr.number} in {pr.owner}/{pr.repo}: **{title}**\n"
                f"URL: {pull.get('html_url', '')}\n\n"
                "### Changed files\n"
                f"{file_summary}\n\n"
                "### Patch excerpt (truncated)\n"
                f"{patch}\n\n"
                "Respond with: Summary, Potential issues, Security considerations, "
                "Test plan suggestions, and Merge recommendation (approve / request changes / comment).\n"
            )
            return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)
        except RuntimeError as e:
            if str(e) == "no_github_auth":
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=github_auth_instructions(),
                )
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"GitHub error: {e}",
            )
        except Exception as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"Failed to load PR for review: {e}",
            )

    if head == "security-review":
        diff = await asyncio.to_thread(run_git_diff, str(root))
        prompt = (
            "You are running a security review of pending changes (clawcode `/security-review`).\n"
            "Analyze the following `git diff` for vulnerabilities, unsafe patterns, secret leakage, "
            "injection risks, auth/authz gaps, and dependency concerns. "
            "Output: Executive summary, Findings (severity-ordered), and Recommended fixes.\n\n"
            "```diff\n"
            f"{diff}\n"
            "```\n"
        )
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)

    if head == "tdd":
        prompt = _build_tdd_prompt(tail)
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)

    if head == "architect":
        args, err = parse_architect_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        prompt = _build_architect_prompt(args)
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)

    if head == "clawteam":
        selected_agent, request, deep_loop, max_iters, err = _parse_clawteam_args(tail)
        if err:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        svc = LearningService(settings)
        selected_roles = [selected_agent] if selected_agent else sorted(_CLAWTEAM_AGENT_CAPABILITIES.keys())[:6]
        tecaps = svc.retrieve_team_capsules_for_clawteam(
            problem_type="general",
            participants=selected_roles,
            team="active-workspace",
            top_k=3,
        )
        tecap_context = [
            {
                "tecap_id": x.tecap_id,
                "score": round(float(x.team_experience_fn.score or 0.0), 6),
                "confidence": round(float(x.team_experience_fn.confidence or 0.0), 6),
                "role_coverage": round(
                    len(
                        {
                            (p.agent_id or "").strip().lower()
                            for p in x.participants
                            if (p.agent_id or "").strip().lower() in {r.lower() for r in selected_roles}
                        }
                    )
                    / max(1, len(selected_roles)),
                    6,
                ),
            }
            for x in tecaps
        ]
        role_ecap_context = svc.retrieve_role_ecaps_for_clawteam(problem_type="general", participants=selected_roles, top_k=1)
        cfg = svc.get_clawteam_deeploop_config()
        domain, _ = resolve_domain(None, {"query": request, "session_title": getattr(ctx, "session_title", "")})
        ts_ms = int(time.time() * 1000)
        trace_id = f"trace-clawteam-{ts_ms}"
        cycle_id = f"cycle-clawteam-{ts_ms}"
        clawteam_deeploop_meta: dict[str, Any] | None = None
        if deep_loop:
            emit_ops_event(
                "clawteam_deeploop_started",
                {
                    "trace_id": trace_id,
                    "cycle_id": cycle_id,
                    "policy_id": "clawteam-deeploop-v1",
                    "domain": domain,
                    "experiment_id": "",
                    "team_id": "active-workspace",
                    "problem_type": "general",
                    "selected_roles": selected_roles,
                    "tecap_id": tecaps[0].tecap_id if tecaps else "",
                },
            )
            role_ecap_map = {
                r: str((role_ecap_context.get(r) or {}).get("ecap_id", "") or "").strip()
                for r in selected_roles
            }
            role_ecap_map = {k: v for k, v in role_ecap_map.items() if v}
            clawteam_deeploop_meta = {
                "trace_id": trace_id,
                "cycle_id": cycle_id,
                "tecap_id": str(tecaps[0].tecap_id if tecaps else ""),
                "role_ecap_map": role_ecap_map,
                "policy_id": "clawteam-deeploop-v1",
                "domain": domain,
                "experiment_id": "",
            }
        prompt = _build_clawteam_prompt(
            request,
            selected_agent,
            deep_loop=deep_loop,
            max_iters=max_iters,
            tecap_context=tecap_context,
            role_ecap_context=role_ecap_context,
            deeploop_thresholds={
                "min_gap_delta": cfg.get("min_gap_delta", 0.05),
                "convergence_rounds": cfg.get("convergence_rounds", 2),
                "handoff_target": cfg.get("handoff_target", 0.85),
            },
        )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            clawteam_deeploop_meta=clawteam_deeploop_meta,
        )

    if head == "clawteam-deeploop-finalize":
        sid = (getattr(ctx, "session_id", "") or "").strip()
        if not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="No active session id in slash context; cannot finalize deep loop writeback.",
            )
        meta = clawteam_deeploop_get_pending(sid)
        if not meta:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "No pending clawteam deep loop metadata for this session.\n\n"
                    "Run **`/clawteam --deep_loop …`** first, then either wait for automatic finalize "
                    "when the assistant includes **`DEEP_LOOP_WRITEBACK_JSON:`**, or paste the assistant "
                    "block after **`/clawteam-deeploop-finalize`** (or omit the tail to use the last "
                    "assistant message from history)."
                ),
            )
        output_text = (tail or "").strip()
        if not output_text and message_service is not None:
            msgs = await message_service.list_by_session(sid, limit=400)
            for m in reversed(msgs):
                if m.role == MessageRole.ASSISTANT:
                    output_text = (m.content or "").strip()
                    break
        if not output_text.strip():
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "No assistant text to parse. Paste the assistant output after the command, "
                    "or ensure the session has a stored assistant message."
                ),
            )
        tecap_id = str(meta.get("tecap_id") or "").strip()
        if not tecap_id:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "Pending deep loop metadata has no `tecap_id` (no team capsule matched). "
                    "Create or import a TECAP, then run **`/clawteam --deep_loop …`** again."
                ),
            )
        role_ecap_raw = meta.get("role_ecap_map")
        role_ecap_map: dict[str, str] = (
            {str(k): str(v) for k, v in dict(role_ecap_raw).items()}
            if isinstance(role_ecap_raw, dict)
            else {}
        )
        svc = LearningService(settings)
        res = svc.finalize_clawteam_deeploop_from_output(
            tecap_id=tecap_id,
            role_ecap_map=role_ecap_map,
            output_text=output_text,
            trace_id=str(meta.get("trace_id") or ""),
            cycle_id=str(meta.get("cycle_id") or ""),
            policy_id=str(meta.get("policy_id") or ""),
            domain=str(meta.get("domain") or ""),
            experiment_id=str(meta.get("experiment_id") or ""),
        )
        if not res.get("skipped"):
            clawteam_deeploop_clear_pending(sid)
        body = (
            "### clawteam deep loop finalize\n\n"
            f"```json\n{json.dumps(res, ensure_ascii=False, indent=2)}\n```\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=body)

    if head == "multi-plan":
        args, err = _parse_multi_plan_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        sub_l = (args.requirement or "").strip().lower()
        store = PlanStore(str(root))
        if sub_l == "show":
            sid = (ctx.session_id or "").strip()
            if not sid:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No active session found. Open a session and run `/multi-plan show` again.",
                )
            bundle = store.find_latest_bundle_for_session_in_subdir(sid, "multi-plan")
            if bundle is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        "No `/multi-plan` artifact found for current session.\n\n"
                        "Run `/multi-plan <requirement>` first."
                    ),
                )
            body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
            if not body.strip():
                body = "(plan markdown is empty)"
            meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
            strategy = str(meta.get("strategy") or "-")
            selected = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
            route_lines: list[str] = []
            for stage, one in sorted(selected.items()):
                if not isinstance(one, dict):
                    continue
                model_id = str(one.get("model_id") or "").strip()
                provider_key = str(one.get("provider_key") or "").strip()
                if model_id:
                    route_lines.append(f"- `{stage}`: `{model_id}` ({provider_key or 'provider?'})")
            route_block = "\n".join(route_lines) if route_lines else "- (no routing metadata)"
            text = (
                f"# latest multi-plan (current session)\n\n"
                f"- markdown: `{bundle.markdown_path}`\n"
                f"- json: `{bundle.json_path}`\n\n"
                f"## Routing summary\n\n"
                f"- strategy: `{strategy}`\n"
                f"{route_block}\n\n"
                f"{body}"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
        if sub_l == "list":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=_format_multi_plan_list(store, limit=200),
            )
        prompt = _build_multi_plan_prompt(args.requirement)
        if prompt.startswith("Usage:"):
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=prompt)
        coder_cfg = settings.get_agent_config("coder")
        routing_meta = build_routing_plan(
            settings,
            args,
            coder_model=str(getattr(coder_cfg, "model", "") or ""),
        )
        if args.explain_routing:
            selected = routing_meta.get("selected_by_stage", {})
            lines: list[str] = []
            if isinstance(selected, dict):
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    mid = str(one.get("model_id") or "").strip()
                    pkey = str(one.get("provider_key") or "").strip()
                    if mid:
                        lines.append(f"- {stage}: `{mid}` ({pkey or 'provider?'})")
            explain = "\n".join(lines) if lines else "- no selection"
            prompt = (
                f"{prompt}\n"
                "Routing decision (config-driven):\n"
                f"- mode: {routing_meta.get('mode')}\n"
                f"- strategy: {routing_meta.get('strategy')}\n"
                f"{explain}\n"
            )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "multi-execute":
        args, err = _parse_multi_execute_args(tail, root=root)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        sub_l = (args.request or "").strip().lower()
        store = PlanStore(str(root))
        if sub_l == "show":
            sid = (ctx.session_id or "").strip()
            if not sid:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No active session found. Open a session and run `/multi-execute show` again.",
                )
            bundle = store.find_latest_bundle_for_session_in_subdir(sid, "multi-execute")
            if bundle is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        "No `/multi-execute` artifact found for current session.\n\n"
                        "Run `/multi-execute <requirement>` or `/multi-execute --from-plan <path>` first."
                    ),
                )
            body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
            if not body.strip():
                body = "(execution markdown is empty)"
            meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
            strategy = str(meta.get("strategy") or "-")
            selected = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
            route_lines: list[str] = []
            for stage, one in sorted(selected.items()):
                if not isinstance(one, dict):
                    continue
                model_id = str(one.get("model_id") or "").strip()
                provider_key = str(one.get("provider_key") or "").strip()
                if model_id:
                    route_lines.append(f"- `{stage}`: `{model_id}` ({provider_key or 'provider?'})")
            route_block = "\n".join(route_lines) if route_lines else "- (no routing metadata)"
            exe = meta.get("execution_meta") if isinstance(meta.get("execution_meta"), dict) else {}
            input_mode = str(exe.get("input_mode") or "-")
            audit = str(exe.get("audit") or "-")
            text = (
                f"# latest multi-execute (current session)\n\n"
                f"- markdown: `{bundle.markdown_path}`\n"
                f"- json: `{bundle.json_path}`\n\n"
                f"## Routing summary\n\n"
                f"- strategy: `{strategy}`\n"
                f"- input_mode: `{input_mode}`\n"
                f"- audit: `{audit}`\n"
                f"{route_block}\n\n"
                f"{body}"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
        if sub_l == "list":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=_format_multi_execute_list(store, limit=200),
            )
        exe_ctx = build_execute_context(
            request=args.request,
            from_plan_path=args.from_plan,
            root=root,
        )
        coder_cfg = settings.get_agent_config("coder")
        assignment = build_model_assignment(
            settings,
            args,
            coder_model=str(getattr(coder_cfg, "model", "") or ""),
        )
        prompt = build_execute_prompt(exe_ctx, assignment, args)
        routing_meta = dict(assignment)
        routing_meta["execution_meta"] = {
            "audit": args.audit,
            "input_mode": exe_ctx.get("input_mode"),
            "from_plan_path": exe_ctx.get("from_plan_path"),
            "task_type": exe_ctx.get("task_type"),
        }
        if args.explain_routing:
            selected = assignment.get("selected_by_stage", {})
            lines: list[str] = []
            if isinstance(selected, dict):
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    mid = str(one.get("model_id") or "").strip()
                    pkey = str(one.get("provider_key") or "").strip()
                    if mid:
                        lines.append(f"- {stage}: `{mid}` ({pkey or 'provider?'})")
            explain = "\n".join(lines) if lines else "- no selection"
            prompt = (
                f"{prompt}\n"
                "Routing decision (config-driven):\n"
                f"- mode: {assignment.get('mode')}\n"
                f"- strategy: {assignment.get('strategy')}\n"
                f"{explain}\n"
            )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "multi-backend":
        rargs, audit_on, err = _parse_multi_backend_args(tail)
        if rargs is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        store = PlanStore(str(root))
        if audit_on is None:
            sub_l = (rargs.requirement or "").strip().lower()
            if sub_l == "show":
                sid = (ctx.session_id or "").strip()
                if not sid:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text="No active session found. Open a session and run `/multi-backend show` again.",
                    )
                bundle = store.find_latest_bundle_for_session_in_subdir(sid, "multi-backend")
                if bundle is None:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=(
                            "No `/multi-backend` artifact found for current session.\n\n"
                            "Run `/multi-backend <backend task>` first."
                        ),
                    )
                body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
                if not body.strip():
                    body = "(markdown is empty)"
                meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
                strategy = str(meta.get("strategy") or "-")
                selected = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
                route_lines: list[str] = []
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    model_id = str(one.get("model_id") or "").strip()
                    provider_key = str(one.get("provider_key") or "").strip()
                    if model_id:
                        route_lines.append(f"- `{stage}`: `{model_id}` ({provider_key or 'provider?'})")
                route_block = "\n".join(route_lines) if route_lines else "- (no routing metadata)"
                be = meta.get("backend_meta") if isinstance(meta.get("backend_meta"), dict) else {}
                audit_s = str(be.get("audit") or "-")
                text = (
                    f"# latest multi-backend (current session)\n\n"
                    f"- markdown: `{bundle.markdown_path}`\n"
                    f"- json: `{bundle.json_path}`\n\n"
                    f"## Routing summary\n\n"
                    f"- workflow: `{meta.get('workflow') or 'backend'}`\n"
                    f"- strategy: `{strategy}`\n"
                    f"- audit: `{audit_s}`\n"
                    f"{route_block}\n\n"
                    f"{body}"
                )
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
            if sub_l == "list":
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=_format_multi_backend_list(store, limit=200),
                )
        req = (rargs.requirement or "").strip()
        coder_cfg = settings.get_agent_config("coder")
        routing_meta = build_backend_routing_meta(
            settings,
            rargs,
            coder_model=str(getattr(coder_cfg, "model", "") or ""),
        )
        routing_meta["backend_meta"] = {"audit": "on" if audit_on else "off"}
        prompt = build_multi_backend_prompt(req, routing_meta, audit_on=bool(audit_on))
        if rargs.explain_routing:
            selected = routing_meta.get("selected_by_stage", {})
            lines_mb: list[str] = []
            if isinstance(selected, dict):
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    mid = str(one.get("model_id") or "").strip()
                    pkey = str(one.get("provider_key") or "").strip()
                    if mid:
                        lines_mb.append(f"- {stage}: `{mid}` ({pkey or 'provider?'})")
            explain_mb = "\n".join(lines_mb) if lines_mb else "- no selection"
            prompt = (
                f"{prompt}\n"
                "Routing decision (config-driven, backend workflow):\n"
                f"- mode: {routing_meta.get('mode')}\n"
                f"- strategy: {routing_meta.get('strategy')}\n"
                f"{explain_mb}\n"
            )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "multi-frontend":
        rargs, audit_on, err = _parse_multi_frontend_args(tail)
        if rargs is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        store = PlanStore(str(root))
        if audit_on is None:
            sub_l = (rargs.requirement or "").strip().lower()
            if sub_l == "show":
                sid = (ctx.session_id or "").strip()
                if not sid:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text="No active session found. Open a session and run `/multi-frontend show` again.",
                    )
                bundle = store.find_latest_bundle_for_session_in_subdir(sid, "multi-frontend")
                if bundle is None:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=(
                            "No `/multi-frontend` artifact found for current session.\n\n"
                            "Run `/multi-frontend <UI task>` first."
                        ),
                    )
                body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
                if not body.strip():
                    body = "(markdown is empty)"
                meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
                strategy = str(meta.get("strategy") or "-")
                selected = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
                route_lines: list[str] = []
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    model_id = str(one.get("model_id") or "").strip()
                    provider_key = str(one.get("provider_key") or "").strip()
                    if model_id:
                        route_lines.append(f"- `{stage}`: `{model_id}` ({provider_key or 'provider?'})")
                route_block = "\n".join(route_lines) if route_lines else "- (no routing metadata)"
                fe = meta.get("frontend_meta") if isinstance(meta.get("frontend_meta"), dict) else {}
                audit_s = str(fe.get("audit") or "-")
                text = (
                    f"# latest multi-frontend (current session)\n\n"
                    f"- markdown: `{bundle.markdown_path}`\n"
                    f"- json: `{bundle.json_path}`\n\n"
                    f"## Routing summary\n\n"
                    f"- workflow: `{meta.get('workflow') or 'frontend'}`\n"
                    f"- strategy: `{strategy}`\n"
                    f"- audit: `{audit_s}`\n"
                    f"{route_block}\n\n"
                    f"{body}"
                )
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
            if sub_l == "list":
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=_format_multi_frontend_list(store, limit=200),
                )
        req = (rargs.requirement or "").strip()
        coder_cfg = settings.get_agent_config("coder")
        routing_meta = build_frontend_routing_meta(
            settings,
            rargs,
            coder_model=str(getattr(coder_cfg, "model", "") or ""),
        )
        routing_meta["frontend_meta"] = {"audit": "on" if audit_on else "off"}
        prompt = build_multi_frontend_prompt(req, routing_meta, audit_on=bool(audit_on))
        if rargs.explain_routing:
            selected = routing_meta.get("selected_by_stage", {})
            lines_mf: list[str] = []
            if isinstance(selected, dict):
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    mid = str(one.get("model_id") or "").strip()
                    pkey = str(one.get("provider_key") or "").strip()
                    if mid:
                        lines_mf.append(f"- {stage}: `{mid}` ({pkey or 'provider?'})")
            explain_mf = "\n".join(lines_mf) if lines_mf else "- no selection"
            prompt = (
                f"{prompt}\n"
                "Routing decision (config-driven, frontend workflow):\n"
                f"- mode: {routing_meta.get('mode')}\n"
                f"- strategy: {routing_meta.get('strategy')}\n"
                f"{explain_mf}\n"
            )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "multi-workflow":
        rargs, audit_on, err = _parse_multi_workflow_args(tail)
        if rargs is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        store = PlanStore(str(root))
        if audit_on is None:
            sub_l = (rargs.requirement or "").strip().lower()
            if sub_l == "show":
                sid = (ctx.session_id or "").strip()
                if not sid:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text="No active session found. Open a session and run `/multi-workflow show` again.",
                    )
                bundle = store.find_latest_bundle_for_session_in_subdir(sid, "multi-workflow")
                if bundle is None:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=(
                            "No `/multi-workflow` artifact found for current session.\n\n"
                            "Run `/multi-workflow <task>` first."
                        ),
                    )
                body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
                if not body.strip():
                    body = "(markdown is empty)"
                meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
                strategy = str(meta.get("strategy") or "-")
                selected = meta.get("selected_by_stage") if isinstance(meta.get("selected_by_stage"), dict) else {}
                route_lines: list[str] = []
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    model_id = str(one.get("model_id") or "").strip()
                    provider_key = str(one.get("provider_key") or "").strip()
                    if model_id:
                        route_lines.append(f"- `{stage}`: `{model_id}` ({provider_key or 'provider?'})")
                route_block = "\n".join(route_lines) if route_lines else "- (no routing metadata)"
                fs = meta.get("fullstack_meta") if isinstance(meta.get("fullstack_meta"), dict) else {}
                audit_s = str(fs.get("audit") or "-")
                text = (
                    f"# latest multi-workflow (current session)\n\n"
                    f"- markdown: `{bundle.markdown_path}`\n"
                    f"- json: `{bundle.json_path}`\n\n"
                    f"## Routing summary\n\n"
                    f"- workflow: `{meta.get('workflow') or 'fullstack'}`\n"
                    f"- strategy: `{strategy}`\n"
                    f"- audit: `{audit_s}`\n"
                    f"{route_block}\n\n"
                    f"{body}"
                )
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
            if sub_l == "list":
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=_format_multi_workflow_list(store, limit=200),
                )
        req = (rargs.requirement or "").strip()
        coder_cfg = settings.get_agent_config("coder")
        routing_meta = build_fullstack_routing_meta(
            settings,
            rargs,
            coder_model=str(getattr(coder_cfg, "model", "") or ""),
        )
        routing_meta["fullstack_meta"] = {"audit": "on" if audit_on else "off"}
        prompt = build_multi_workflow_prompt(req, routing_meta, audit_on=bool(audit_on))
        if rargs.explain_routing:
            selected = routing_meta.get("selected_by_stage", {})
            lines_mw: list[str] = []
            if isinstance(selected, dict):
                for stage, one in sorted(selected.items()):
                    if not isinstance(one, dict):
                        continue
                    mid = str(one.get("model_id") or "").strip()
                    pkey = str(one.get("provider_key") or "").strip()
                    if mid:
                        lines_mw.append(f"- {stage}: `{mid}` ({pkey or 'provider?'})")
            explain_mw = "\n".join(lines_mw) if lines_mw else "- no selection"
            prompt = (
                f"{prompt}\n"
                "Routing decision (config-driven, full-stack workflow):\n"
                f"- mode: {routing_meta.get('mode')}\n"
                f"- strategy: {routing_meta.get('strategy')}\n"
                f"{explain_mw}\n"
            )
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "orchestrate":
        oargs, err = parse_orchestrate_args(tail)
        if oargs is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        if oargs.show_list == "show":
            store = PlanStore(str(root))
            sid = (ctx.session_id or "").strip()
            if not sid:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No active session found. Open a session and run `/orchestrate show` again.",
                )
            bundle = store.find_latest_bundle_for_session_in_subdir(sid, "orchestrate")
            if bundle is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        "No `/orchestrate` artifact found for current session.\n\n"
                        "Run `/orchestrate <workflow> <task>` first."
                    ),
                )
            body = store.load_markdown(bundle.markdown_path) or bundle.plan_text
            if not body.strip():
                body = "(markdown is empty)"
            meta = bundle.routing_meta if isinstance(getattr(bundle, "routing_meta", None), dict) else {}
            otype = str(meta.get("orchestrate_type") or "-")
            chain = meta.get("orchestrate_chain")
            if isinstance(chain, list):
                chain_s = " → ".join(str(x) for x in chain)
            else:
                chain_s = str(chain or "-")
            text = (
                f"# latest orchestrate (current session)\n\n"
                f"- markdown: `{bundle.markdown_path}`\n"
                f"- json: `{bundle.json_path}`\n\n"
                f"## Summary\n\n"
                f"- workflow: `{meta.get('workflow') or 'orchestrate'}`\n"
                f"- type: `{otype}`\n"
                f"- chain: `{chain_s}`\n\n"
                f"{body}"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
        if oargs.show_list == "list":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=_format_orchestrate_list(PlanStore(str(root)), limit=200),
            )
        prompt = build_orchestrate_prompt(
            workflow=oargs.workflow, agents=oargs.agents, task=oargs.task
        )
        routing_meta = {
            "workflow": "orchestrate",
            "orchestrate_type": oargs.workflow,
            "orchestrate_chain": list(oargs.agents),
        }
        return BuiltinSlashOutcome(
            kind="agent_prompt",
            agent_user_text=prompt,
            routing_meta=routing_meta,
        )

    if head == "learn":
        svc = LearningService(settings)
        if "--observe" in (tail or ""):
            txt = await asyncio.to_thread(svc.run_observer_once)
        else:
            txt = await asyncio.to_thread(svc.learn_from_recent_observations)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "closed-loop-contract":
        svc = LearningService(settings)
        report = await asyncio.to_thread(svc.closed_loop_contract_report)
        tokens = set(shlex.split(tail or ""))
        as_json = "--json" in tokens
        consumed = report.get("consumed_keys", report.get("consumed", []))
        unconsumed = report.get("unconsumed_keys", report.get("unconsumed", []))
        consumed_count = int(report.get("consumed_count", len(consumed)) or 0)
        unconsumed_count = int(report.get("unconsumed_count", len(unconsumed)) or 0)
        if as_json:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=json.dumps(
                    {
                        "schema_version": str(report.get("schema_version", "closed-loop-contract-v1")),
                        "total_keys": int(report.get("total_keys", consumed_count + unconsumed_count) or 0),
                        "consumed_count": consumed_count,
                        "unconsumed_count": unconsumed_count,
                        "consumed_keys": consumed,
                        "unconsumed_keys": unconsumed,
                        "risk_level": str(report.get("risk_level", "unknown")),
                        "recommended_action": str(report.get("recommended_action", "")),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        text = (
            "# Closed Loop Config Contract\n\n"
            f"- schema_version: {report.get('schema_version', 'closed-loop-contract-v1')}\n"
            f"- consumed_count: {consumed_count}\n"
            f"- unconsumed_count: {unconsumed_count}\n"
            f"- risk_level: {report.get('risk_level', 'unknown')}\n"
            f"- recommended_action: {report.get('recommended_action', '')}\n"
            f"- consumed: {consumed}\n"
            f"- unconsumed: {unconsumed}\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "instinct-status":
        svc = LearningService(settings)
        args, err = parse_status_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.status_text, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "instinct-import":
        svc = LearningService(settings)
        args, err = parse_import_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.import_instincts_advanced, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "instinct-export":
        svc = LearningService(settings)
        args, err = parse_export_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.export_instincts_advanced, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "evolve":
        svc = LearningService(settings)
        args, err = parse_evolve_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.evolve_advanced, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "learn-orchestrate":
        svc = LearningService(settings)
        dry_run = False
        as_json = False
        report_mode = False
        report_only = False
        apply_tuning = False
        export_report = False
        explicit_domain: str | None = None
        window_hours = int(getattr(settings.closed_loop, "tuning_window_hours", 24) or 24)
        filtered: list[str] = []
        raw_tokens = shlex.split(tail or "")
        idx = 0
        while idx < len(raw_tokens):
            tok = raw_tokens[idx]
            if tok == "--dry-run":
                dry_run = True
            elif tok == "--json":
                as_json = True
            elif tok == "--report":
                report_mode = True
            elif tok == "--report-only":
                report_only = True
            elif tok == "--apply-tuning":
                apply_tuning = True
            elif tok == "--export-report":
                export_report = True
            elif tok == "--domain" and idx + 1 < len(raw_tokens):
                idx += 1
                explicit_domain = str(raw_tokens[idx]).strip().lower() or None
            elif tok == "--window" and idx + 1 < len(raw_tokens):
                idx += 1
                try:
                    window_hours = max(1, min(24 * 30, int(raw_tokens[idx])))
                except ValueError:
                    window_hours = int(getattr(settings.closed_loop, "tuning_window_hours", 24) or 24)
            else:
                filtered.append(tok)
            idx += 1
        evolve_args, err = parse_evolve_args(" ".join(filtered))
        if evolve_args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        if report_only:
            dry_run = True
        cycle = await asyncio.to_thread(
            svc.run_autonomous_cycle,
            evolve_args=evolve_args,
            dry_run=dry_run,
            report_only=report_only,
            apply_tuning=apply_tuning,
            export_report=export_report,
            explicit_domain=explicit_domain,
            window_hours=window_hours,
            import_limit=12,
        )
        if as_json:
            contract_report = await asyncio.to_thread(svc.closed_loop_contract_report)
            cycle_errors = cycle.get("errors", [])
            taxonomy: dict[str, int] = {}
            if isinstance(cycle_errors, list):
                for e in cycle_errors:
                    if isinstance(e, dict):
                        stage = str(e.get("stage", "unknown") or "unknown")
                    else:
                        stage = "unknown"
                    taxonomy[stage] = taxonomy.get(stage, 0) + 1
            payload = dict(cycle)
            payload["contract_report"] = contract_report
            payload["error_taxonomy"] = taxonomy
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=json.dumps(payload, ensure_ascii=False, indent=2),
            )
        import_payload = cycle.get("import_payload", {"summary": {}})
        summary = import_payload.get("summary", {}) if isinstance(import_payload, dict) else {}
        cycle_schema_version = str(cycle.get("schema_version", "autonomous-cycle-v1"))
        mode_line = str(cycle.get("mode", "apply"))
        domain = str(cycle.get("domain", "general"))
        domain_conf = float(cycle.get("domain_confidence", 0.0) or 0.0)
        predicted = int(cycle.get("predicted_import_candidates", 0) or 0)
        observe_txt = str(cycle.get("observe", ""))
        evolve_txt = str(cycle.get("evolve", ""))
        observe_status = str(cycle.get("observe_status", "unknown"))
        evolve_status = str(cycle.get("evolve_status", "unknown"))
        import_status = str(cycle.get("import_status", "unknown"))
        report_status = str(cycle.get("report_status", "unknown"))
        tuning_status = str(cycle.get("tuning_status", "unknown"))
        export_status = str(cycle.get("export_status", "unknown"))
        cycle_errors = cycle.get("errors", [])
        ops_report = cycle.get("ops_report", {}) if isinstance(cycle.get("ops_report"), dict) else {}
        tuning_report = cycle.get("tuning_report", {}) if isinstance(cycle.get("tuning_report"), dict) else {}
        layered_report = cycle.get("layered_report", {}) if isinstance(cycle.get("layered_report"), dict) else {}
        long_term_metrics = cycle.get("long_term_metrics", {}) if isinstance(cycle.get("long_term_metrics"), dict) else {}
        canary_eval = cycle.get("canary_evaluation", {}) if isinstance(cycle.get("canary_evaluation"), dict) else {}
        runbook = cycle.get("runbook", {}) if isinstance(cycle.get("runbook"), dict) else {}
        applied_tuning = cycle.get("applied_tuning") if isinstance(cycle.get("applied_tuning"), dict) else None
        exported_report = cycle.get("exported_report") if isinstance(cycle.get("exported_report"), dict) else None
        contract_report = await asyncio.to_thread(svc.closed_loop_contract_report)
        result = (
            "# Learning Orchestration\n\n"
            f"- schema_version: {cycle_schema_version}\n"
            f"- mode: {mode_line}\n"
            f"- observe: {observe_txt}\n"
            f"- evolve: {evolve_txt}\n"
            "- stage_status:\n"
            f"  - observe: {observe_status}\n"
            f"  - evolve: {evolve_status}\n"
            f"  - import: {import_status}\n"
            f"  - report: {report_status}\n"
            f"  - tuning: {tuning_status}\n"
            f"  - export: {export_status}\n"
            "- import-to-claw-skills:\n"
            f"  - created: {summary.get('created', 0)}\n"
            f"  - updated: {summary.get('updated', 0)}\n"
            f"  - skipped_same_content: {summary.get('skipped_same_content', 0)}\n"
            f"  - conflicts: {summary.get('conflicts', 0)}\n"
            f"  - read_errors: {summary.get('read_errors', 0)}\n"
        )
        if dry_run or report_mode or report_only or apply_tuning:
            result += (
                "- report:\n"
                f"  - window_hours: {window_hours}\n"
                f"  - domain: {domain}\n"
                f"  - domain_confidence: {domain_conf:.2f}\n"
                f"  - predicted_import_candidates: {predicted}\n"
                f"  - executed_import: {'no' if dry_run else 'yes'}\n"
                f"  - metrics_event_count: {ops_report.get('event_count', 0)}\n"
                f"  - metrics_counts: {ops_report.get('counts', {})}\n"
                f"  - tuning_recommendations: {len(tuning_report.get('recommendations', []))}\n"
                f"  - cycle_error_count: {len(cycle_errors) if isinstance(cycle_errors, list) else 0}\n"
                f"  - contract_consumed_keys: {contract_report.get('consumed_count', 0)}\n"
                f"  - contract_unconsumed_keys: {contract_report.get('unconsumed_count', 0)}\n"
                f"  - long_term_windows: {list((long_term_metrics.get('windows', {}) or {}).keys())}\n"
                f"  - canary_decision: {canary_eval.get('decision', 'hold')}\n"
                f"  - canary_state: {canary_eval.get('state', 'n/a')}\n"
                f"  - canary_experiment_id: {canary_eval.get('experiment_id', '')}\n"
                f"  - canary_delta: {canary_eval.get('absolute_delta', 0.0)}\n"
                f"  - canary_confidence: {canary_eval.get('confidence', 0.0)}\n"
                f"  - canary_reason: {canary_eval.get('reason', '')}\n"
                f"  - canary_report_ref: {canary_eval.get('report_ref', '')}\n"
                f"  - slo_state: {cycle.get('slo_state', '')}\n"
                f"  - freeze_reason: {cycle.get('freeze_reason', '')}\n"
                f"  - policy_id: {cycle.get('policy_id', '')}\n"
                f"  - runbook_code: {runbook.get('code', 'OK')}\n"
            )
            result += layered_report.get("markdown_report", "") + "\n"
            if applied_tuning is not None:
                result += f"  - tuning_applied: {applied_tuning.get('applied', [])}\n"
            elif apply_tuning:
                result += "  - tuning_applied: skipped (tuning_auto_apply_enabled=false)\n"
            if exported_report is not None:
                if exported_report.get("success"):
                    result += (
                        f"  - exported_report_md: {exported_report.get('md_path', '')}\n"
                        f"  - exported_report_json: {exported_report.get('json_path', '')}\n"
                    )
                else:
                    result += f"  - exported_report: {exported_report.get('skipped', 'failed')}\n"
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=result)

    if head == "experience-dashboard":
        svc = LearningService(settings)
        raw_tokens = shlex.split(tail or "")
        tokens = set(raw_tokens)
        as_json = "--json" in tokens
        no_alerts = "--no-alerts" in tokens
        domain: str | None = None
        idx = 0
        while idx < len(raw_tokens):
            if raw_tokens[idx] == "--domain" and idx + 1 < len(raw_tokens):
                idx += 1
                domain = str(raw_tokens[idx]).strip().lower() or None
            idx += 1
        snap = await asyncio.to_thread(svc.experience_dashboard_query, include_alerts=not no_alerts, domain=domain)
        if as_json:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=json.dumps(snap, ensure_ascii=False, indent=2),
            )
        dash = snap.get("experience_dashboard", {}) if isinstance(snap.get("experience_dashboard"), dict) else {}
        metrics = dash.get("metrics", {}) if isinstance(dash.get("metrics"), dict) else {}
        wm = dash.get("window_metrics", {}) if isinstance(dash.get("window_metrics"), dict) else {}
        al = snap.get("experience_alerts", {}) if isinstance(snap.get("experience_alerts"), dict) else {}
        policy = snap.get("experience_policy_advice", {}) if isinstance(snap.get("experience_policy_advice"), dict) else {}
        lines: list[str] = [
            "# ECAP-first Experience Dashboard\n\n",
            f"- query_schema_version: {snap.get('schema_version', 'experience-dashboard-query-v1')}\n",
            f"- dashboard_schema_version: {dash.get('schema_version', '')}\n",
            f"- generated_at: {dash.get('generated_at', '')}\n",
            f"- experience_health: {snap.get('experience_health', 'ok')}\n\n",
            "## Current metrics\n\n",
        ]
        for k in sorted(metrics.keys()):
            lines.append(f"- {k}: {metrics.get(k)}\n")
        lines.append("\n## Window metrics\n\n")
        for wk in sorted(wm.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            sub = wm.get(wk, {})
            if not isinstance(sub, dict):
                continue
            lines.append(f"### {wk} day(s)\n")
            for kk in sorted(sub.keys()):
                lines.append(f"- {kk}: {sub.get(kk)}\n")
            lines.append("\n")
        lines.append("## Alerts\n\n")
        lines.append(f"- level: {al.get('level', 'ok')}\n")
        for row in list(al.get("alerts", []) or [])[:24]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"  - {row.get('metric')}: {row.get('level')} "
                f"value={row.get('value')} ({row.get('reason', '')})\n"
            )
        lines.append("\n## Adaptive policy advice\n\n")
        lines.append(f"- guard_mode: {policy.get('guard_mode', 'normal')}\n")
        for row in list(policy.get("suggestions", []) or [])[:12]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"  - {row.get('target')}: {row.get('op')} "
                f"delta/value={row.get('delta', row.get('value', ''))} ({row.get('reason', '')})\n"
            )
        abx = dash.get("ab_comparison", {}) if isinstance(dash.get("ab_comparison"), dict) else {}
        if abx:
            lines.append("\n## A/B comparison\n\n")
            lines.append(f"- enabled: {abx.get('enabled', False)}\n")
            lines.append(f"- delta: {abx.get('delta', 0.0)}\n")
            lines.append(f"- buckets: {abx.get('buckets', {})}\n")
        lines.append("\n*Tip:* `/experience-dashboard --json` for machine-readable output; "
                     "`--no-alerts` skips alert evaluation (metrics only).\n")
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "experience-create":
        svc = LearningService(settings)
        args, err = parse_experience_create_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.create_experience, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "experience-status":
        svc = LearningService(settings)
        args, err = parse_experience_status_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.experience_status, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "experience-export":
        svc = LearningService(settings)
        args, err = parse_experience_export_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.experience_export, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "experience-import":
        svc = LearningService(settings)
        args, err = parse_experience_import_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.experience_import, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "experience-apply":
        svc = LearningService(settings)
        args, err = parse_experience_apply_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        ok, payload = await asyncio.to_thread(svc.build_experience_apply_prompt, args)
        if not ok:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=payload)
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=payload)

    if head == "experience-feedback":
        svc = LearningService(settings)
        args, err = parse_experience_feedback_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.experience_feedback, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "team-experience-create":
        svc = LearningService(settings)
        args, err = parse_team_experience_create_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.create_team_experience, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "team-experience-status":
        svc = LearningService(settings)
        args, err = parse_team_experience_status_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.team_experience_status, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "team-experience-export":
        svc = LearningService(settings)
        args, err = parse_team_experience_export_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.team_experience_export, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "team-experience-import":
        svc = LearningService(settings)
        args, err = parse_team_experience_import_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.team_experience_import, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "team-experience-apply":
        svc = LearningService(settings)
        args, err = parse_team_experience_apply_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        ok, payload = await asyncio.to_thread(svc.build_team_experience_apply_prompt, args)
        if not ok:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=payload)
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=payload)

    if head == "team-experience-feedback":
        svc = LearningService(settings)
        args, err = parse_team_experience_feedback_args(tail)
        if args is None:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=err)
        txt = await asyncio.to_thread(svc.team_experience_feedback, args)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=txt)

    if head == "code-review":
        prompt = _build_code_review_prompt(tail)
        return BuiltinSlashOutcome(kind="agent_prompt", agent_user_text=prompt)

    if head == "statusline":
        text = (
            "**clawcode status line**\n\n"
            "The TUI already shows session/model/tool activity in the bottom HUD bar.\n\n"
            "There is no separate shell PS1/RPM statusline integration shipped with clawcode. "
            "To mirror session info in an external terminal, use your shell theme or a prompt "
            "plugin, and optionally read clawcode session metadata from your own scripts.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "stats":
        cw_line = (
            f"- **Context window (approx.):** {ctx.context_window_size:,} tokens\n"
            if ctx.context_window_size
            else "- **Context window (approx.):** (unknown for this model)\n"
        )
        lines = [
            "# clawcode stats\n\n",
            "## Usage (this session)\n\n",
            f"- **Model:** {ctx.model_label or '(unknown)'}\n",
            cw_line,
            f"- **Context fill (estimate):** {ctx.context_percent}%\n",
            f"- **Session tokens (DB):** prompt {ctx.session_prompt_tokens:,} · "
            f"completion {ctx.session_completion_tokens:,}\n",
            f"- **This turn (live):** input {ctx.turn_input_tokens:,} · "
            f"output {ctx.turn_output_tokens:,}\n\n",
            "## Recent activity\n\n",
        ]
        if session_service is None:
            lines.append("Session database not available.\n")
        else:
            sessions = await session_service.list(limit=12)
            if not sessions:
                lines.append("No sessions recorded.\n")
            else:
                lines.append("| Title | Msgs | Prompt tok | Completion tok | Cost |\n")
                lines.append("| --- | ---: | ---: | ---: | ---: |\n")
                for s in sessions:
                    lines.append(
                        f"| {s.title[:48]} | {s.message_count} | {s.prompt_tokens} | "
                        f"{s.completion_tokens} | {s.cost:.4f} |\n"
                    )
        lines.append(
            "\nFor a full table use `/insights`. The HUD shows live context while you chat.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "status":
        sid = (ctx.session_id or "").strip()
        sid_short = (f"`{sid[:10]}…`" if len(sid) > 10 else f"`{sid}`") if sid else "(none)"
        lines = [
            "# clawcode status\n\n",
            f"- **App version:** {ctx.app_version or 'unknown'}\n",
            f"- **Display mode:** {ctx.display_mode or 'default'}\n",
            f"- **Workspace:** {ctx.working_dir_display or '(unknown)'}\n",
            f"- **Session:** {ctx.session_title or '(untitled)'} · id {sid_short}\n",
            f"- **Model:** {ctx.model_label or '(unknown)'} ({ctx.provider_label or 'provider?'})\n",
            f"- **LSP:** {'on' if ctx.lsp_on else 'off'}\n",
            f"- **Mouse mode:** {'on' if ctx.mouse_on else 'off'}\n",
            f"- **Auto-compact:** {'on' if ctx.auto_compact else 'off'}\n",
            f"- **Agent:** {'processing' if ctx.is_agent_processing else 'idle'}\n\n",
            "**API / connectivity:** clawcode does not ping providers from this view. "
            "If chat and tools work, your configured API is reachable. "
            "Check keys and `base_url` in settings if requests fail.\n",
        ]
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "stickers":
        text = (
            "**clawcode stickers**\n\n"
            "There is no in-app sticker shop. Enjoy clawcode in the terminal, "
            "and share the project with anyone who likes ASCII-friendly tools.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "tasks":
        lines = ["# Background tasks\n\n"]
        lines.append(
            f"- **Agent conversation run:** {'**busy** (model streaming or tools)' if ctx.is_agent_processing else 'idle'}\n\n"
        )
        if ctx.plan_background_tasks:
            lines.append("## Plan build tasks (current session)\n\n")
            for ln in ctx.plan_background_tasks:
                lines.append(f"- {ln}\n")
        else:
            lines.append(
                "No plan-build task list for this session. "
                "Start `/plan` and approve a build to see tasks here.\n"
            )
        lines.append(
            "\nUse the plan panel buttons to resume or stop an active build when available.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "terminal-setup":
        text = (
            "**Terminal setup (newlines in chat input)**\n\n"
            "clawcode uses **backslash (\\\\) + Enter** to insert a newline without sending. "
            "A plain **Enter** sends the message.\n\n"
            "**Shift+Enter** is not installed by clawcode; behavior depends on your terminal. "
            "Configure your emulator (e.g. iTerm2, Windows Terminal) if you want Shift+Enter "
            "to send a different sequence.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "theme":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="",
            ui_action="show_theme_selector",
        )

    if head == "release-notes":
        text = await asyncio.to_thread(_release_notes_markdown)
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "rename":
        if not (ctx.session_id or "").strip():
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="No active session to rename.",
            )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="",
            ui_action="show_rename_dialog",
        )

    if head == "resume":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="",
            ui_action="switch_session",
        )

    if head == "rewind":
        parts = tail.strip().split()
        if not parts:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=_REWIND_HELP)

        sub = parts[0].lower()
        if sub == "help":
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=_REWIND_HELP)

        if sub == "chat":
            if message_service is None or session_service is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="Message or session service is not available (database not initialized).",
                )
            sid = (ctx.session_id or "").strip()
            if not sid:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No active session. Open or select a session first.",
                )
            if len(parts) < 2:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="Usage: `/rewind chat last` or `/rewind chat <message_id>`\n",
                )
            if parts[1] == "last":
                anchor = await message_service.last_active_user_message_id(sid)
                if anchor is None:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text="No user messages to anchor on; nothing was archived.\n",
                    )
                n = await message_service.soft_delete_messages_after(sid, anchor, inclusive=False)
                await message_service.reconcile_session_row_from_active_messages(sid, session_service)
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        f"Archived **{n}** message(s) after the last user turn (soft-delete in DB).\n"
                        "The chat view will reload.\n"
                    ),
                    ui_action="reload_session_history",
                )

            anchor_id = parts[1]
            n = await message_service.soft_delete_messages_after(sid, anchor_id, inclusive=False)
            if n == 0:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        "No messages archived. Check that the id is an active message in this session "
                        "and that there are messages after it.\n"
                    ),
                )
            await message_service.reconcile_session_row_from_active_messages(sid, session_service)
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    f"Archived **{n}** message(s) after `{anchor_id}` (soft-delete in DB).\n"
                    "The chat view will reload.\n"
                ),
                ui_action="reload_session_history",
            )

        if sub == "git":
            if not is_git_repo(root):
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"**Git:** `{root}` is not inside a git work tree.\n",
                )
            if len(parts) == 1:
                por, perr = await asyncio.to_thread(git_status_porcelain_summary, root)
                stat, serr = await asyncio.to_thread(git_diff_stat, root)
                lines = ["# Git (read-only)\n\n"]
                if perr:
                    lines.append(f"**status error:** {perr}\n\n")
                else:
                    lines.append("## status --porcelain\n\n")
                    lines.append(f"```\n{por or '(clean)'}\n```\n\n")
                if serr:
                    lines.append(f"**diff error:** {serr}\n")
                else:
                    lines.append("## diff --stat HEAD\n\n")
                    lines.append(f"```\n{stat or '(no diff)'}\n```\n")
                lines.append(
                    "\nUse `/rewind git restore` to reset **tracked** files to HEAD (with confirmation). "
                    "Untracked files are **not** removed.\n"
                )
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

            if len(parts) >= 2 and parts[1].lower() == "restore":
                paths, err = await asyncio.to_thread(git_tracked_paths_differing_from_head, root)
                if err:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=f"**Git:** could not list changed paths: {err}\n",
                    )
                if not paths:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text="No tracked paths differ from HEAD; nothing to restore.\n",
                    )
                preview = "\n".join(f"- `{p}`" for p in paths[:30])
                if len(paths) > 30:
                    preview += f"\n- … **{len(paths) - 30}** more"
                text = (
                    "**Git restore**\n\n"
                    f"The following **{len(paths)}** tracked path(s) differ from HEAD "
                    "(staged and/or worktree):\n\n"
                    f"{preview}\n\n"
                    "A confirmation dialog will open. **Untracked files are not affected.**\n"
                )
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=text,
                    ui_action="confirm_git_restore",
                    git_restore_cwd=str(root),
                    git_restore_paths=paths,
                )

            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Unknown git subcommand. Use `/rewind git` or `/rewind git restore`.\n",
            )

        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=f"Unknown rewind target `{sub!s}`. Try `/rewind` for help.\n",
        )

    if head == "checkpoint":
        try:
            parts = shlex.split((tail or "").strip())
        except ValueError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"Invalid `/checkpoint` args: {e}\n",
            )
        if not parts or parts[0].lower() in {"help", "-h", "--help"}:
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=_CHECKPOINT_HELP)
        sub = parts[0].lower()
        if sub == "list":
            text, err = await asyncio.to_thread(format_list_text, root)
            if err:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not read checkpoint log: {err}\n",
                )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
        if sub == "clear":
            kept, err = await asyncio.to_thread(clear_keep_last_n, root, 5)
            if err:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not trim checkpoint log: {err}\n",
                )
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"Checkpoint log trimmed: **{kept}** entr(y/ies) kept (last 5).\n"
                f"Path: `{checkpoint_log_path(root)}`\n",
            )
        if sub == "verify":
            if len(parts) < 2:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="Usage: `/checkpoint verify <name>`\n",
                )
            vname = " ".join(parts[1:]).strip()
            verr = validate_checkpoint_name(vname)
            if verr:
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=f"{verr}\n")
            if not is_git_repo(root):
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"**Git:** `{root}` is not inside a git work tree.\n",
                )
            text, err = await asyncio.to_thread(format_verify_report, root, vname)
            if err:
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=f"{err}\n")
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)
        if sub == "create":
            cname, do_stash, cerr = _parse_checkpoint_create_args(parts[1:])
            if cerr or not cname:
                return BuiltinSlashOutcome(kind="assistant_message", assistant_text=f"{cerr or 'Invalid create.'}\n")
            if not is_git_repo(root):
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"**Git:** `{root}` is not inside a git work tree.\n",
                )
            if do_stash:
                ok_st, st_err = await asyncio.to_thread(
                    git_stash_push_message,
                    root,
                    f"clawcode-checkpoint: {cname}",
                )
                if not ok_st:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=f"**stash failed** (no checkpoint written): {st_err}\n",
                    )
            short, rev_err = await asyncio.to_thread(git_rev_parse_short, root)
            if rev_err or not short:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not read HEAD: {rev_err or 'unknown'}\n",
                )
            line = format_log_line(name=cname, short_sha=short)
            aerr = await asyncio.to_thread(append_checkpoint_line, root, line)
            if aerr:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not write checkpoint log: {aerr}\n",
                )
            stash_note = "\n\nStashed local changes with `git stash push` before recording.\n" if do_stash else ""
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    f"**Checkpoint created:** `{cname}` @ `{short}`\n\n"
                    f"Log: `{checkpoint_log_path(root)}`{stash_note}\n"
                    "Tip: run tests or `/doctor` before risky edits if you want a known-good baseline.\n"
                ),
            )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Unknown `/checkpoint` subcommand `{sub!s}`.\n\n{_CHECKPOINT_HELP}"
            ),
        )

    if head == "skills":
        lines: list[str] = ["# Available skills (clawcode)\n\n"]
        if plugin_manager is None:
            lines.append("Plugin manager is not available in this view.\n")
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        skills = plugin_manager.get_all_skills()
        if not skills:
            lines.append(
                "No skills loaded. Enable plugins in settings and add plugins with SKILL.md "
                "under project or user plugin directories.\n"
            )
        else:
            for sk in skills:
                desc = (sk.description or "").strip().replace("\n", " ")
                head_line = f"- **`/{sk.name}`** (`{sk.plugin_name}`)"
                if desc:
                    head_line += f" — {desc}"
                lines.append(head_line + "\n")
        lines.append("\nSkills are also invocable as `/skill-name` when loaded.\n")
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "memory":
        cp = list(getattr(settings, "context_paths", None) or [])
        claw_md = root / "CLAWCODE.md"
        cfg_file = root / ".clawcode.json"
        lines = [
            "# Claw memory (project context)\n\n",
            f"- **Primary project context file:** `{claw_md}` — edit in an external editor or run `/init` "
            "to bootstrap a template.\n",
            f"- **Settings:** `{cfg_file}` — models, `context_paths`, and other clawcode options.\n\n",
        ]
        if cp:
            lines.append("## Extra context paths (from settings)\n\n")
            for p in cp[:24]:
                lines.append(f"- `{p}`\n")
            if len(cp) > 24:
                lines.append(f"- … **{len(cp) - 24}** more\n")
            lines.append("\n")
        else:
            lines.append(
                "No `context_paths` in settings; add file globs or paths in `.clawcode.json` "
                "to load more context into the agent.\n\n"
            )
        lines.append("Plugin **SKILL.md** entries extend what the agent knows; see `/skills`.\n")
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "mobile":
        text = (
            "**Claw mobile app**\n\n"
            "clawcode does not ship an official claw mobile app or app-store download link yet, "
            "so there is no QR code to scan here.\n\n"
            "For mobile use, run clawcode over **SSH** or a remote development environment from your device.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "model":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="",
            ui_action="open_model_dialog",
        )

    if head == "output-style":
        mode_norm_to_key = {m.key.lower(): m.key for m in _DISPLAY_MODE_ITEMS}
        key = tail.strip().lower()
        if not key:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="",
                ui_action="open_display_mode",
            )
        if key in mode_norm_to_key:
            canon = mode_norm_to_key[key]
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"Output style set to **{canon}**.\n",
                apply_display_mode=canon,
            )
        valid = ", ".join(f"`{m.key}`" for m in _DISPLAY_MODE_ITEMS)
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Unknown output style `{tail.strip()}`. Valid modes: {valid}.\n\n"
                "Opening the display mode picker. Shortcut: **Ctrl+D**.\n"
            ),
            ui_action="open_display_mode",
        )

    if head == "ui-style":
        parts = tail.strip().split()
        sub = (parts[0].lower() if parts else "status").strip()
        arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
        styles = load_ui_catalog(root, cli_launch_directory=_ui_cli_host)
        if sub in ("on", "off"):
            mode = "on" if sub == "on" else "off"
            try:
                save_ui_style_mode_to_clawcode_json(mode, working_directory=str(root))
            except Exception:
                # best-effort persistence; session update still applies.
                pass
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    f"UI style mode set to **{mode}**.\n"
                    "When `on`, UI-related tasks must select a style before coding.\n"
                ),
                routing_meta={"ui_style": {"mode": mode}},
            )
        if sub == "set":
            slug = arg.strip()
            if not slug:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="Usage: `/ui-style set <slug>`\n",
                )
            known = {s.slug: s for s in styles}
            if known and slug not in known:
                sample = ", ".join(sorted(list(known.keys()))[:10])
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Unknown style slug `{slug}`.\nTry `/ui-style list`.\nExamples: {sample}\n",
                )
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"UI style locked to **{slug}** (source=user).\n",
                routing_meta={"ui_style": {"selected": slug, "source": "user", "reason": "user set"}},
            )
        if sub == "auto":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cleared manual style selection. Next UI task will auto-pick.\n",
                routing_meta={"ui_style": {"selected": "", "source": "auto", "reason": "manual cleared"}},
            )
        if sub == "list":
            q = arg.lower()
            rows = [s for s in styles if not q or q in s.slug.lower() or q in s.role.lower() or q in " ".join(s.tags).lower()]
            lines = ["# UI styles\n\n"]
            if not rows:
                lines.append("No style found.\n")
                hints = ui_catalog_candidate_hints(root, cli_launch_directory=_ui_cli_host)
                if hints:
                    lines.append(
                        "Catalog lookup paths:\n"
                        + "".join(f"- `{p}`\n" for p in hints[:3])
                        + "If none exists, run: `py -3 scripts/build_ui_style_catalog.py`\n"
                    )
            else:
                for st in rows[:80]:
                    tags = f" ({', '.join(st.tags[:4])})" if st.tags else ""
                    role = f" — {st.role}" if st.role else ""
                    lines.append(f"- `{st.slug}`{role}{tags}\n")
            lines.append("\nUse `/ui-style set <slug>` to pin one.\n")
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        if sub == "show":
            slug = arg.strip() or (ctx.ui_style_selected or "").strip()
            if not slug:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="Usage: `/ui-style show <slug>` (or select one first).\n",
                )
            hit = next((s for s in styles if s.slug == slug), None)
            if hit is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Unknown style slug `{slug}`.\n",
                )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=format_ui_style_compact(hit))
        if sub == "eval":
            slug = (ctx.ui_style_selected or "").strip()
            if not slug:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=(
                        "No selected UI style.\n"
                        "Use `/ui-style set <slug>` first, or send a UI task with `/ui-style auto`.\n"
                    ),
                )
            hit = next((s for s in styles if s.slug == slug), None)
            if hit is None:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Unknown selected style `{slug}`.\n",
                )
            source_text = arg
            if not source_text:
                sid = (ctx.session_id or "").strip()
                if not sid or message_service is None:
                    return BuiltinSlashOutcome(
                        kind="assistant_message",
                        assistant_text=(
                            "Usage: `/ui-style eval <ui-output-text>`\n"
                            "Or run within an active session to auto-read last assistant message.\n"
                        ),
                    )
                try:
                    msgs = await message_service.list_by_session(sid, limit=80)
                except Exception:
                    msgs = []
                last_assistant = next((m for m in reversed(msgs) if str(getattr(m, "role", "")).lower().endswith("assistant")), None)
                source_text = _message_text_body(last_assistant) if last_assistant is not None else ""
            if not source_text.strip():
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No assistant output text found for evaluation.\n",
                )
            anti = load_ui_anti_patterns(root, slug=hit.slug, cli_launch_directory=_ui_cli_host)
            anti_rules = load_ui_anti_pattern_rules(
                root, slug=hit.slug, cli_launch_directory=_ui_cli_host
            )
            next_best = choose_secondary_ui_style_candidate(
                source_text,
                styles,
                top_candidates=list(ctx.ui_style_top_candidates or []),
            )
            ev = evaluate_ui_style_text(
                source_text,
                hit,
                anti_patterns=anti,
                anti_rules=anti_rules,
                next_best_slug=(next_best[0] if next_best is not None else ""),
            )
            lines = [
                "# UI style eval\n\n",
                f"- slug: `{ev.slug}`\n",
                f"- color_consistency: `{ev.color_consistency}`\n",
                f"- component_semantics: `{ev.component_semantics}`\n",
                f"- tone_consistency: `{ev.tone_consistency}`\n",
                f"- token_hit_rate: `{ev.token_hit_rate}` ({ev.token_hits}/{ev.token_total})\n",
                f"- anti_pattern_penalty: `{ev.anti_pattern_penalty}`\n",
                f"- selection_risk: `{ev.selection_risk}`\n",
            ]
            if ev.next_best_slug:
                lines.append(f"- next_best_slug: `{ev.next_best_slug}`\n")
            if ev.matched_anti_patterns:
                lines.append("- matched_anti_patterns:\n")
                lines.extend(f"  - {x}\n" for x in ev.matched_anti_patterns[:8])
            if ev.repair_actions:
                lines.append("- repair_actions:\n")
                lines.extend(f"  - {x}\n" for x in ev.repair_actions[:8])
            if ev.notes:
                lines.append("- notes:\n")
                lines.extend(f"  - {x}\n" for x in ev.notes[:8])
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        if sub == "why":
            lines = [
                "# UI style selection reason\n\n",
                f"- mode: `{ctx.ui_style_mode or 'off'}`\n",
                f"- selected: `{ctx.ui_style_selected or '(none)'}`\n",
                f"- source: `{ctx.ui_style_source or '(unknown)'}`\n",
                "\n## Detail\n\n",
                f"{ctx.ui_style_reason or '(none)'}\n\n",
            ]
            if ctx.ui_style_top_candidates:
                n = len(ctx.ui_style_top_candidates)
                lines.append(f"- top_candidates (top {n} by raw score): ")
                lines.append(", ".join(ctx.ui_style_top_candidates) + "\n")
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                "Usage:\n"
                "- `/ui-style on|off`\n"
                "- `/ui-style set <slug>`\n"
                "- `/ui-style auto`\n"
                "- `/ui-style list [keyword]`\n"
                "- `/ui-style show [slug]`\n"
                "- `/ui-style eval [ui-output-text]`\n"
                "- `/ui-style why`\n"
            ),
        )

    if head == "permissions":
        parts = tail.strip().split()
        if parts and parts[0].lower() == "clear":
            sid = (ctx.session_id or "").strip()
            if not sid:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text="No active session; nothing to clear.\n",
                )
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "Cleared **session-scoped** tool allows for this conversation. "
                    "The next restricted tool runs will ask for approval again.\n"
                ),
                clear_session_tool_permissions=True,
            )
        perm_text = (
            "# Tool permissions (clawcode)\n\n"
            "When the agent runs a tool, clawcode may show an **allow / deny** prompt "
            "(once per call or **for this session**).\n\n"
            "- **Session allow** remembers that tool name until you clear it or leave the session.\n"
            "- This build has **no** separate on-disk allow/deny rule file; control is interactive.\n\n"
            "Use **`/permissions clear`** to drop session-scoped tool allows for the current session.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=perm_text)

    if head == "ide":
        ide_text = (
            "# IDE integrations (clawcode)\n\n"
            "clawcode is a **terminal TUI**. This build does **not** ship a dedicated IDE status "
            "panel or proprietary editor bridge.\n\n"
            "Practical pairing:\n\n"
            "- **LSP:** configure language servers under `lsp` in `.clawcode.json` for in-TUI features.\n"
            "- **External editor:** set `tui.external_editor` if you open files from clawcode.\n"
            "- **Workspace:** open the same folder in your IDE while you run clawcode in a terminal.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=ide_text)

    if head == "install-github-app":
        gh_text = (
            "**claw GitHub Actions**\n\n"
            "There is no one-click installer for an official **claw** GitHub Action in this build.\n\n"
            "To automate checks, add your own workflow under `.github/workflows/`, use repository "
            "secrets for tokens (never commit `GITHUB_TOKEN` or API keys), and keep scopes minimal.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=gh_text)

    if head == "install-slack-app":
        slack_text = (
            "**claw Slack app**\n\n"
            "There is no bundled **claw** Slack app install flow in clawcode.\n\n"
            "For Slack integrations, create a Slack app in your workspace, store bot tokens as "
            "secrets, and wire webhooks or API calls from your own infrastructure—do not paste "
            "tokens into chat logs.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=slack_text)

    if head == "login":
        login_text = (
            "**Sign in (Anthropic and other providers)**\n\n"
            "clawcode does **not** use an in-app “Sign in with Anthropic” OAuth flow.\n\n"
            "Configure credentials in **`.clawcode.json`** under `providers` (e.g. `api_key`) and/or "
            "matching **environment variables** such as `ANTHROPIC_API_KEY`, depending on which "
            "provider slot your agent uses. Use **Ctrl+O** to pick model/provider after keys are set.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=login_text)

    if head == "logout":
        logout_text = (
            "**Sign out**\n\n"
            "There is no session-style logout inside the TUI.\n\n"
            "To stop using a key: **unset** the relevant environment variables, **remove or clear** "
            "`api_key` fields in `.clawcode.json`, or **rotate** keys at your provider. clawcode does "
            "not modify your config files automatically from this command.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=logout_text)

    if head == "claude":
        from ..llm.claw_support import anthropic_resolve as _ar

        token_ok = bool(_ar.resolve_anthropic_token())
        cred_line = (
            "**Anthropic credential resolved:** yes (Console key, OAuth, or Claude Code file — "
            "not shown).\n\n"
            if token_ok
            else "**Anthropic credential resolved:** no — set `ANTHROPIC_API_KEY` / `ANTHROPIC_TOKEN` / "
            "`CLAUDE_CODE_OAUTH_TOKEN` or `~/.claude/.credentials.json` (see `anthropic_resolve`).\n\n"
        )
        core = (
            "**Claude Code path A (Claw mode)**\n\n"
            "This command **turns on Claw agent mode** (same as `/claw on`), then you use "
            "in-process **Anthropic Messages** with HTTP headers aligned to the Claude Code CLI "
            "(beta, `user-agent`, Bearer vs `x-api-key`). This is **not** spawning the `claude` "
            "binary — use **`/claude-cli`** for path B (subprocess).\n\n"
            f"{cred_line}"
            "Configure provider + model in **`.clawcode.json`** / **Ctrl+O**. "
            "Details: `claw_support/CLAW_SUPPORT_MAP.md`, `ANTHROPIC_CLAUDE_COMPAT.md`.\n"
        )
        if ctx.plan_blocks_claw:
            blocked = (
                "**Cannot enable Claw mode** while /plan is pending. "
                "Run **`/plan off`** first, then **`/claude`** again.\n\n"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=blocked + core)
        tail_note = (
            "\n\n**Claw agent mode is now ON** (same as `/claw on`). "
            "Subsequent turns use `ClawAgent.run_claw_turn` and the Claw tool stack, not the default coder path.\n"
        )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=core + tail_note,
            ui_action="enable_claw_mode",
        )

    if head == "claude-cli":
        from ..llm.claw_support.claude_cli_bridge import (
            ClaudeCLIError,
            resolve_claude_cli_terminal_backend,
            resolve_claude_executable,
            run_claude_cli,
        )

        term_backend = resolve_claude_cli_terminal_backend()
        intro_common = (
            "**Path B — official Claude Code CLI**\n\n"
            "This command **turns on Claw agent mode** (same as `/claw on`), then runs "
            "`claude` / `claude-code` in the **configured terminal backend** "
            f"(``CLAWCODE_TERMINAL_ENV`` / ``TERMINAL_ENV`` → **{term_backend}**), "
            "from the **current workspace** (skills and docs out-of-process). "
            "Same stack as the bash tool when environments backend is enabled. "
            "Use **`/claude`** for path A (in-process API) without spawning the CLI. "
            "See `claw_support/CLAW_SUPPORT_MAP.md`.\n\n"
        )
        if ctx.plan_blocks_claw:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "**Cannot enable Claw mode** while /plan is pending. "
                    "Run **`/plan off`** first, then **`/claude-cli`** again.\n"
                ),
            )

        tail_s = (tail or "").strip()
        if not tail_s:
            cli_args: list[str] = ["--version"]
            note = "No arguments — defaulting to `--version` (path B probe).\n\n"
        else:
            try:
                cli_args = shlex.split(tail_s, posix=os.name != "nt")
            except ValueError as e:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not parse arguments: {e}\n",
                    ui_action="enable_claw_mode",
                )
            note = ""

        exe = resolve_claude_executable()
        exe_line = f"`{exe}`" if exe else "(not found on host PATH)"
        if term_backend != "local" and not exe:
            exe_line = (
                "(not on host PATH — will use `claude` in the backend environment; "
                "ensure the image/remote has the CLI installed)"
            )

        intro = (
            f"{intro_common}"
            f"- **Terminal backend:** `{term_backend}`\n"
            f"- **Resolved executable (host):** {exe_line}\n"
            f"- **Working directory:** `{root}`\n\n"
        )

        if not exe and term_backend == "local":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro
                + "Install Claude Code CLI and ensure it is on `PATH`, then retry.\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        try:
            code, out, err = await run_claude_cli(
                cli_args,
                cwd=root,
                timeout=120.0,
                session_id=(ctx.session_id or "").strip() or None,
            )
        except ClaudeCLIError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro
                + note
                + f"**Error:** {e}\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        out_block = (out or "").strip() or "(empty)"
        err_block = (err or "").strip() or "(empty)"
        body = (
            f"{intro}{note}"
            f"**Exit code:** `{code}`\n\n"
            "**stdout**\n```\n" + out_block + "\n```\n\n"
            "**stderr**\n```\n" + err_block + "\n```\n\n"
            "**Claw agent mode is now ON** (same as `/claw on`).\n"
        )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=body,
            ui_action="enable_claw_mode",
        )

    if head == "opencode-cli":
        from ..llm.claw_support.opencode_cli_bridge import (
            OpenCodeCLIError,
            resolve_opencode_cli_terminal_backend,
            resolve_opencode_executable,
            run_opencode_cli,
        )

        term_backend = resolve_opencode_cli_terminal_backend()
        intro_common = (
            "**Path B′ — OpenCode CLI**\n\n"
            "This command **turns on Claw agent mode** (same as `/claw on`), then runs "
            "the **`opencode`** binary in the **configured terminal backend** "
            f"(``CLAWCODE_TERMINAL_ENV`` / ``TERMINAL_ENV`` → **{term_backend}**), "
            "from the **current workspace**. "
            "Same stack as the bash tool when environments backend is enabled. "
            "Use **`/claude-cli`** for Anthropic's `claude` CLI; **`/claude`** for path A (in-process API). "
            "See `claw_support/CLAW_SUPPORT_MAP.md`.\n\n"
        )
        if ctx.plan_blocks_claw:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "**Cannot enable Claw mode** while /plan is pending. "
                    "Run **`/plan off`** first, then **`/opencode-cli`** again.\n"
                ),
            )

        tail_s = (tail or "").strip()
        if not tail_s:
            cli_args_oc: list[str] = ["--version"]
            note_oc = "No arguments — defaulting to `--version` (path B′ probe).\n\n"
        else:
            try:
                cli_args_oc = shlex.split(tail_s, posix=os.name != "nt")
            except ValueError as e:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not parse arguments: {e}\n",
                    ui_action="enable_claw_mode",
                )
            note_oc = ""

        exe_oc = resolve_opencode_executable()
        exe_line_oc = f"`{exe_oc}`" if exe_oc else "(not found on host PATH)"
        if term_backend != "local" and not exe_oc:
            exe_line_oc = (
                "(not on host PATH — will use `opencode` in the backend environment; "
                "ensure the image/remote has the CLI installed)"
            )

        intro_oc = (
            f"{intro_common}"
            f"- **Terminal backend:** `{term_backend}`\n"
            f"- **Resolved executable (host):** {exe_line_oc}\n"
            f"- **Working directory:** `{root}`\n\n"
        )

        if not exe_oc and term_backend == "local":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro_oc
                + "Install OpenCode CLI and ensure `opencode` is on `PATH`, then retry.\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        try:
            code_oc, out_oc, err_oc = await run_opencode_cli(
                cli_args_oc,
                cwd=root,
                timeout=120.0,
                session_id=(ctx.session_id or "").strip() or None,
            )
        except OpenCodeCLIError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro_oc
                + note_oc
                + f"**Error:** {e}\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        out_block_oc = (out_oc or "").strip() or "(empty)"
        err_block_oc = (err_oc or "").strip() or "(empty)"
        body_oc = (
            f"{intro_oc}{note_oc}"
            f"**Exit code:** `{code_oc}`\n\n"
            "**stdout**\n```\n" + out_block_oc + "\n```\n\n"
            "**stderr**\n```\n" + err_block_oc + "\n```\n\n"
            "**Claw agent mode is now ON** (same as `/claw on`).\n"
        )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=body_oc,
            ui_action="enable_claw_mode",
        )

    if head == "codex-cli":
        from ..llm.claw_support.codex_cli_bridge import (
            CodexCLIError,
            resolve_codex_cli_terminal_backend,
            resolve_codex_executable,
            run_codex_cli,
        )

        term_backend_cdx = resolve_codex_cli_terminal_backend()
        intro_common_cdx = (
            "**Path B″ — OpenAI Codex CLI**\n\n"
            "This command **turns on Claw agent mode** (same as `/claw on`), then runs "
            "the **`codex`** binary in the **configured terminal backend** "
            f"(``CLAWCODE_TERMINAL_ENV`` / ``TERMINAL_ENV`` → **{term_backend_cdx}**), "
            "from the **current workspace**. "
            "Same stack as the bash tool when environments backend is enabled. "
            "Use **`/claude-cli`** for Anthropic's `claude` CLI; **`/opencode-cli`** for OpenCode. "
            "See `claw_support/CLAW_SUPPORT_MAP.md`.\n\n"
        )
        if ctx.plan_blocks_claw:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "**Cannot enable Claw mode** while /plan is pending. "
                    "Run **`/plan off`** first, then **`/codex-cli`** again.\n"
                ),
            )

        tail_s_cdx = (tail or "").strip()
        if not tail_s_cdx:
            cli_args_cdx: list[str] = ["--version"]
            note_cdx = "No arguments — defaulting to `--version` (path B″ probe).\n\n"
        else:
            try:
                cli_args_cdx = shlex.split(tail_s_cdx, posix=os.name != "nt")
            except ValueError as e:
                return BuiltinSlashOutcome(
                    kind="assistant_message",
                    assistant_text=f"Could not parse arguments: {e}\n",
                    ui_action="enable_claw_mode",
                )
            note_cdx = ""

        exe_cdx = resolve_codex_executable()
        exe_line_cdx = f"`{exe_cdx}`" if exe_cdx else "(not found on host PATH)"
        if term_backend_cdx != "local" and not exe_cdx:
            exe_line_cdx = (
                "(not on host PATH — will use `codex` in the backend environment; "
                "ensure the image/remote has the CLI installed)"
            )

        intro_cdx = (
            f"{intro_common_cdx}"
            f"- **Terminal backend:** `{term_backend_cdx}`\n"
            f"- **Resolved executable (host):** {exe_line_cdx}\n"
            f"- **Working directory:** `{root}`\n\n"
        )

        if not exe_cdx and term_backend_cdx == "local":
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro_cdx
                + "Install Codex CLI (`npm install -g @openai/codex`) and ensure `codex` is on `PATH`, "
                "then retry.\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        try:
            code_cdx, out_cdx, err_cdx = await run_codex_cli(
                cli_args_cdx,
                cwd=root,
                timeout=120.0,
                session_id=(ctx.session_id or "").strip() or None,
            )
        except CodexCLIError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=intro_cdx
                + note_cdx
                + f"**Error:** {e}\n\n"
                "**Claw agent mode is now ON** (same as `/claw on`).\n",
                ui_action="enable_claw_mode",
            )

        out_block_cdx = (out_cdx or "").strip() or "(empty)"
        err_block_cdx = (err_cdx or "").strip() or "(empty)"
        body_cdx = (
            f"{intro_cdx}{note_cdx}"
            f"**Exit code:** `{code_cdx}`\n\n"
            "**stdout**\n```\n" + out_block_cdx + "\n```\n\n"
            "**stderr**\n```\n" + err_block_cdx + "\n```\n\n"
            "**Claw agent mode is now ON** (same as `/claw on`).\n"
        )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=body_cdx,
            ui_action="enable_claw_mode",
        )

    if head == "mcp":
        servers = getattr(settings, "mcp_servers", None) or {}
        lines = [
            "# MCP servers (configuration)\n\n",
            "Connections are created when the agent/MCP stack runs; this list reflects **settings only**.\n\n",
        ]
        if not servers:
            lines.append(
                "No MCP servers in settings. Add a `mcp_servers` map in `.clawcode.json` "
                "(name → command/args or url).\n"
            )
        else:
            for name in sorted(servers.keys()):
                srv = servers[name]
                mtype = getattr(getattr(srv, "type", None), "value", None) or str(
                    getattr(srv, "type", "?")
                )
                url = getattr(srv, "url", None)
                if url:
                    lines.append(f"- **`{name}`** — type `{mtype}` — url `{url}`\n")
                else:
                    cmd = (getattr(srv, "command", "") or "").strip()
                    parts = [cmd, *list(getattr(srv, "args", None) or [])]
                    summary = " ".join(p for p in parts if p).strip() or "(no command)"
                    if len(summary) > 140:
                        summary = summary[:137] + "…"
                    lines.append(f"- **`{name}`** — type `{mtype}` — `{summary}`\n")
            lines.append("\n`headers` and other secrets are not printed here.\n")
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "exit":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="Exiting clawcode…",
            ui_action="exit_app",
        )

    if head == "export":
        sid = (ctx.session_id or "").strip()
        if message_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot export: no active session or message service unavailable.\n",
            )
        rows = await message_service.list_by_session(sid, limit=_EXPORT_LIST_LIMIT)
        if not rows:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Nothing to export in this session.\n",
            )
        tail_l = tail.strip().lower()
        want_file = tail_l.startswith("file")
        parts_md: list[str] = ["# clawcode conversation export\n\n", f"Session: `{sid}`\n\n"]
        total = 0
        included = 0
        for i, msg in enumerate(rows):
            chunk = _export_message_markdown(msg)
            if total + len(chunk) > _EXPORT_TOTAL_MAX:
                omitted = len(rows) - i
                parts_md.append(
                    f"\n\n_(Export truncated: **{omitted}** message(s) not included "
                    "due to size limit.)_\n"
                )
                break
            parts_md.append(chunk)
            total += len(chunk)
            included += 1
        body = "".join(parts_md)
        note = (
            f"Copied **{included}** message block(s) "
            f"({len(body):,} characters) to the clipboard.\n"
        )
        if want_file:
            note += (
                "\n**File export** is not implemented in this build; the same Markdown was copied "
                "to the clipboard — paste into a file and save.\n"
            )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=note,
            clipboard_text=body,
        )

    if head == "fast":
        fast_text = (
            "**Fast mode (clawcode)**\n\n"
            "There is no single “fast mode” toggle tied to a specific vendor model in clawcode.\n\n"
            "To move faster: pick a quicker model with **Ctrl+O**, lower `max_tokens` for the agent "
            "in `.clawcode.json`, and rely on your provider’s latency and quotas.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=fast_text)

    if head == "fork":
        sid = (ctx.session_id or "").strip()
        if session_service is None or message_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot fork: no active session or database services unavailable.\n",
            )
        rows = await message_service.list_by_session(sid, limit=_EXPORT_LIST_LIMIT)
        base_title = (ctx.session_title or "Chat").strip() or "Chat"
        fork_title = f"Fork of {base_title}"[:120]
        new_sess = await session_service.create(fork_title, parent_session_id=sid)
        new_id = new_sess.id
        n_copied = 0
        for msg in rows:
            cloned = _clone_parts_for_fork(list(msg.parts or []))
            text = (msg.content or "").strip()
            if cloned:
                await message_service.create(
                    new_id,
                    msg.role,
                    content="",
                    parts=cloned,
                    model=msg.model,
                )
                n_copied += 1
            elif text:
                await message_service.create(
                    new_id,
                    msg.role,
                    content=text,
                    model=msg.model,
                )
                n_copied += 1
        await message_service.reconcile_session_row_from_active_messages(new_id, session_service)
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Forked **{n_copied}** message(s) into a new session "
                f"(from **{len(rows)}** in the source).\n\n"
                f"Switching to **`{new_id}`**…\n"
            ),
            switch_to_session_id=new_id,
        )

    if head == "help":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="Opening help…",
            ui_action="show_help_screen",
        )

    if head == "hooks":
        lines = ["# Plugin hooks (tool-related events)\n\n"]
        if plugin_manager is None:
            lines.append("Plugin manager is not available in this view.\n")
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        plugins = [p for p in plugin_manager.plugins if p.enabled]
        if not plugins:
            lines.append(
                "No enabled plugins loaded. Enable plugins in settings to use hook JSON under "
                "each plugin’s `hooks/` directory.\n"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))
        for p in sorted(plugins, key=lambda x: x.name):
            if not p.hooks:
                lines.append(f"- **`{p.name}`** — no hooks configured\n")
                continue
            for ev, groups in sorted(p.hooks.items(), key=lambda kv: kv[0].value):
                n = len(groups)
                matchers = [g.matcher[:48] for g in groups[:3] if g.matcher]
                ms = ", ".join(f"`{m}`" for m in matchers) if matchers else "(default)"
                if len(groups) > 3:
                    ms += f", … **{n}** group(s)"
                lines.append(
                    f"- **`{p.name}`** · `{ev.value}` — {n} matcher group(s): {ms}\n"
                )
        lines.append(
            "\nEdit `hooks/hooks.json` (or manifest `hooks`) inside each plugin folder; "
            "this TUI does not provide a hook GUI.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "context":
        bar = _context_ascii_bar(ctx.context_percent)
        bar2 = _context_ascii_bar(ctx.context_percent, width=20)
        cw = (
            f"{ctx.context_window_size:,} tokens"
            if ctx.context_window_size
            else "(unknown)"
        )
        text = (
            "# Context usage (HUD-aligned)\n\n"
            f"Approximate **fill:** **{ctx.context_percent}%** of the model context window.\n\n"
            "## ASCII grid (10 cells)\n\n"
            f"```\n{bar}\n```\n\n"
            "## Finer bar (20 cells)\n\n"
            f"```\n{bar2}\n```\n\n"
            f"- **Context window (approx.):** {cw}\n"
            f"- **Session tokens (DB):** prompt {ctx.session_prompt_tokens:,} · "
            f"completion {ctx.session_completion_tokens:,}\n"
            f"- **This turn (live):** input {ctx.turn_input_tokens:,} · "
            f"output {ctx.turn_output_tokens:,}\n"
            f"- **Model:** {ctx.model_label or '(unknown)'}\n\n"
            "This is a terminal-friendly visualization, not a pixel heatmap.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=text)

    if head == "copy":
        from ..message.service import MessageRole

        sid = (ctx.session_id or "").strip()
        if message_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot copy: no active session or message service unavailable.\n",
            )
        rows = await message_service.list_by_session(sid, limit=_EXPORT_LIST_LIMIT)
        last_asst = None
        for msg in reversed(rows):
            if msg.role == MessageRole.ASSISTANT:
                last_asst = msg
                break
        if last_asst is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="No assistant message found in this session yet.\n",
            )
        md = _export_message_markdown(last_asst)
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text="Copied the last **claw** assistant reply to the clipboard (Markdown).\n",
            clipboard_text=md,
        )

    if head == "cost":
        sid = (ctx.session_id or "").strip()
        if session_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot show cost: no active session or session service unavailable.\n",
            )
        sess = await session_service.get(sid)
        if sess is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Session not found in the database.\n",
            )
        now = int(time.time())
        dur = _format_duration(now - int(sess.created_at or now))
        lines = [
            "# Session cost (clawcode)\n\n",
            f"- **Session:** {ctx.session_title or sess.title or '(untitled)'}\n",
            f"- **Estimated duration:** {dur} (since session `created_at`)\n",
            f"- **Total cost (USD, DB):** {sess.cost:.6f}\n",
            f"- **Messages (DB count):** {sess.message_count}\n",
            f"- **Tokens (DB):** prompt {sess.prompt_tokens:,} · completion {sess.completion_tokens:,}\n\n",
            "Costs depend on provider billing; DB totals are best-effort aggregates.\n",
        ]
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "desktop":
        desk = (
            "**claw Desktop**\n\n"
            "clawcode is a **terminal TUI**. There is no official “claw Desktop” client that "
            "continues this session with one click.\n\n"
            "To keep working elsewhere: use **`/export`** to copy the conversation, or open the "
            "same project in another environment and configure the same `.clawcode.json` providers.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=desk)

    if head == "diff":
        tl = tail.strip().lower()
        if tl in ("help", "?", "per-turn", "perturn"):
            htext = (
                "# Diff (clawcode)\n\n"
                "## Workspace (git)\n\n"
                "Use **`/diff`** with no arguments for `git status` and `git diff --stat` against HEAD "
                "(same idea as `/rewind git`).\n\n"
                "## Per-turn diffs\n\n"
                "Turn-by-turn file diffs are **not** stored in this build’s chat database. "
                "Use workspace git, editor local history, or future `FileChange` tooling when available.\n"
            )
            return BuiltinSlashOutcome(kind="assistant_message", assistant_text=htext)
        if not is_git_repo(root):
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"**Git:** `{root}` is not inside a git work tree.\n",
            )
        por, perr = await asyncio.to_thread(git_status_porcelain_summary, root)
        stat, serr = await asyncio.to_thread(git_diff_stat, root)
        lines = ["# Diff (git, read-only)\n\n"]
        if perr:
            lines.append(f"**status error:** {perr}\n\n")
        else:
            lines.append("## status --porcelain\n\n")
            lines.append(f"```\n{por or '(clean)'}\n```\n\n")
        if serr:
            lines.append(f"**diff error:** {serr}\n")
        else:
            lines.append("## diff --stat HEAD\n\n")
            lines.append(f"```\n{stat or '(no diff)'}\n```\n")
        lines.append(
            "\nFor **per-turn** diffs inside chat, see **`/diff help`**.\n"
            "Tracked restore: **`/rewind git restore`** (with confirmation).\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "add-dir":
        raw_tail = (tail or "").strip()
        if not raw_tail:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "# Add directory (clawcode)\n\n"
                    "Usage: **`/add-dir <path>`** — appends an absolute directory to `context_paths` in "
                    "`.clawcode.json` (merge write under your workspace).\n\n"
                    "Example: `/add-dir ../other-repo`\n\n"
                    "You may need to **restart** the TUI so loaded settings pick up new paths.\n"
                ),
            )
        try:
            written = append_context_path_to_clawcode_json(
                raw_tail,
                working_directory=str(root),
            )
        except ValueError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"**`/add-dir`:** {e}\n",
            )
        except TypeError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"**`/add-dir`:** config error: {e}\n",
            )
        except OSError as e:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"**`/add-dir`:** could not write config: {e}\n",
            )
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Added directory to **`context_paths`** in `{written}`.\n"
                "Restart clawcode if the session does not reload config automatically.\n"
            ),
        )

    if head == "agents":
        agents_map = getattr(settings, "agents", None) or {}
        lines = ["# Agent configurations (clawcode)\n\n"]
        if not agents_map:
            lines.append(
                "No `agents` map in the loaded settings. Define slots in **`.clawcode.json`**.\n\n"
            )
        else:
            for name, acfg in sorted(agents_map.items(), key=lambda kv: str(kv[0])):
                model_s = str(getattr(acfg, "model", "") or "").strip() or "(unknown)"
                pk = str(getattr(acfg, "provider_key", "") or "").strip()
                prov_bit = f" · provider **`{pk}`**" if pk else ""
                lines.append(f"- **`{name}`** — model **`{model_s}`**{prov_bit}\n")
        lines.append(
            "\n**Ctrl+O** opens the model picker (persists the primary coder slot when saved).\n"
            "For tool limits and models per role, edit **`agents`** in `.clawcode.json`.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    if head == "chrome":
        chrome_txt = (
            "# Claw in Chrome (Beta)\n\n"
            "This build does **not** ship a Chrome extension or “Claw in Chrome” pairing UI.\n\n"
            "Use the **clawcode terminal TUI** here, or tune **`tui.external_editor`**, **LSP**, and "
            "workspace roots in **`.clawcode.json`** for an editor-focused workflow.\n"
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text=chrome_txt)

    if head == "clear":
        sid = (ctx.session_id or "").strip()
        if message_service is None or session_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot clear: no active session or database services unavailable.\n",
            )
        msgs = await message_service.list_by_session(sid, limit=10_000)
        if not msgs:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Nothing to clear — this session has no active messages.\n",
            )
        n = await message_service.soft_delete_messages_after(sid, msgs[0].id, inclusive=True)
        await message_service.reconcile_session_row_from_active_messages(sid, session_service)
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Cleared **{n}** message(s) from this session (soft-archived). "
                "Context counters will refresh after reload.\n"
            ),
            ui_action="reload_session_history",
        )

    if head == "compact":
        from ..history.summarizer import SummarizerService
        from ..config.constants import AgentName
        from ..llm.providers import create_provider, resolve_provider_from_model

        sid = (ctx.session_id or "").strip()
        if message_service is None or session_service is None or not sid:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text="Cannot compact: no active session or database services unavailable.\n",
            )
        msgs = await message_service.list_by_session(sid, limit=10_000)
        keep_n = 4
        if len(msgs) <= keep_n:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    f"**`/compact`** needs more than **{keep_n}** active messages "
                    "so older turns can be summarized while keeping recent ones.\n"
                ),
            )
        last_err: Exception | None = None
        result = None

        # Attempt 1: summarizer agent (default path).
        try:
            summ_svc = SummarizerService(settings, message_service, session_service)
            result = await summ_svc.force_summarize(
                sid,
                msgs,
                keep_recent=keep_n,
                extra_user_instructions=tail.strip(),
            )
        except Exception as e:
            last_err = e

        # Attempt 2: summarizer provider missing/invalid → fall back to current effective provider.
        if result is None:
            try:
                effective_model = (ctx.model_label or "").strip() or settings.get_agent_config(
                    AgentName.CODER
                ).model
                coder_cfg = settings.get_agent_config(AgentName.CODER)
                provider_name, provider_key = resolve_provider_from_model(
                    effective_model, settings, coder_cfg
                )
                prov_cfg = (settings.providers or {}).get(provider_key)
                if (
                    prov_cfg
                    and not getattr(prov_cfg, "disabled", False)
                    and (getattr(prov_cfg, "api_key", None) or "").strip()
                ):
                    fallback_provider = create_provider(
                        provider_name=provider_name,
                        model_id=effective_model,
                        api_key=prov_cfg.api_key,
                        max_tokens=coder_cfg.max_tokens,
                        base_url=getattr(prov_cfg, "base_url", None),
                        timeout=getattr(prov_cfg, "timeout", 120),
                    )
                    summ_svc2 = SummarizerService(
                        settings,
                        message_service,
                        session_service,
                        provider=fallback_provider,
                    )
                    result = await summ_svc2.force_summarize(
                        sid,
                        msgs,
                        keep_recent=keep_n,
                        extra_user_instructions=tail.strip(),
                    )
            except Exception as e:
                last_err = e

        # Attempt 3: last-resort degrade — force truncate input (so Summarizer can chunk/trim).
        if result is None:
            try:
                max_total_msgs = 200
                truncated = msgs[-min(len(msgs), max_total_msgs) :]
                summ_svc3 = SummarizerService(settings, message_service, session_service)
                result = await summ_svc3.force_summarize(
                    sid,
                    truncated,
                    keep_recent=min(keep_n, max(1, len(truncated) - 1)),
                    extra_user_instructions=tail.strip(),
                )
            except Exception as e:
                last_err = e

        if last_err is not None and result is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=f"**`/compact` failed:** {last_err}\n",
            )
        if result is None:
            return BuiltinSlashOutcome(
                kind="assistant_message",
                assistant_text=(
                    "**`/compact`:** summarizer returned no result "
                    "(check provider API keys and the `summarizer` agent model in settings).\n"
                ),
            )
        keep_ids = frozenset({result.summary_message.id, *(m.id for m in msgs[-keep_n:])})
        n_arch = await message_service.soft_delete_messages_except_ids(sid, keep_ids)
        await message_service.reconcile_session_row_from_active_messages(sid, session_service)
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                f"Compacted: added a **[SUMMARY]** system message and archived **{n_arch}** older "
                "message(s). Recent turns are preserved.\n"
            ),
            ui_action="reload_session_history",
        )

    if head == "config":
        return BuiltinSlashOutcome(
            kind="assistant_message",
            assistant_text=(
                "Opening **`.clawcode.json`** for this workspace in your external editor "
                "(see `tui.external_editor`).\n"
            ),
            ui_action="open_clawcode_config_external",
        )

    if head == "doctor":
        cfg_path = root / ".clawcode.json"
        cfg_ok = cfg_path.is_file()
        cfg_note = f"`{cfg_path}` — **present**" if cfg_ok else f"`{cfg_path}` — **missing**"
        prov = getattr(settings, "providers", None) or {}
        n_slots = len(prov)
        n_keys = sum(1 for p in prov.values() if (getattr(p, "api_key", None) or "").strip())
        mcp_n = len(getattr(settings, "mcp_servers", None) or {})
        plug = getattr(settings, "plugins", None)
        plug_on = bool(plug and getattr(plug, "enabled", True))
        db_line = (
            "Session/message **database** is available to this view (handler received `session_service`).\n"
            if session_service is not None
            else "**session_service** was not passed — database status unknown from this handler.\n"
        )
        lines = [
            "# Doctor (clawcode)\n\n",
            f"- **App version (HUD):** {ctx.app_version or 'unknown'}\n",
            f"- **Workspace:** `{root}`\n",
            f"- **Config:** {cfg_note}\n",
            f"- **Provider slots (`providers`):** {n_slots} · with non-empty `api_key`: **{n_keys}**\n",
            f"- **MCP servers (settings):** {mcp_n}\n",
            f"- **Plugins.enabled:** {plug_on}\n\n",
            db_line,
        ]
        try:
            from ..llm.tools.desktop.desktop_utils import check_desktop_requirements_detail

            _fc: bool | None = None
            if getattr(settings.desktop, "tools_require_claw_mode", False):
                _fc = bool(getattr(ctx, "claw_mode_enabled", False))
            d_ok, d_reason = check_desktop_requirements_detail(for_claw_mode=_fc)
        except Exception as e:
            d_ok, d_reason = False, f"desktop check failed: {e}"
        d_status = "**ok**" if d_ok else "**not ok**"
        d_extra = f" — {d_reason}" if d_reason else ""
        lines.append(
            f"- **Desktop tools:** {d_status}{d_extra}\n\n"
            "\nThis is a **best-effort** checklist, not a full network probe. "
            "If chat fails, verify API keys and `base_url` for your provider slot.\n",
        )
        return BuiltinSlashOutcome(kind="assistant_message", assistant_text="".join(lines))

    return BuiltinSlashOutcome(
        kind="assistant_message",
        assistant_text=f"Unknown built-in command: /{head}",
    )
