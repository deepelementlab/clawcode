"""Research-scoped tool registry with optional plugin hook fan-out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...learning.paths import ensure_learning_dirs
from ..sandbox.base import Sandbox
from .code_audit import audit_claims_vs_code
from .paper import paper_search_stub
from .sandbox_tools import sandbox_run_command
from .search import web_search_stub
from .web import fetch_url_stub

# JSON-schema style parameter specs for provider tool lists
_SCHEMA_WEB = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query string."},
        "num_results": {
            "type": "integer",
            "description": "Maximum number of results to return.",
            "default": 5,
        },
    },
    "required": ["query"],
}

_SCHEMA_PAPER = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Paper search query."},
        "source": {
            "type": "string",
            "description": "Index to search: arxiv or semantic_scholar.",
            "default": "arxiv",
        },
    },
    "required": ["query"],
}

_SCHEMA_FETCH = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "HTTP(S) URL to fetch and extract text from."},
    },
    "required": ["url"],
}

_SCHEMA_SANDBOX = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to run inside the research sandbox workspace.",
        },
    },
    "required": ["command"],
}

_SCHEMA_AUDIT = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "string"}},
        "repo_path": {"type": "string"},
    },
    "required": ["claims", "repo_path"],
}


@dataclass
class ResearchTool:
    name: str
    description: str
    handler: Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]
    requires_sandbox: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(
        self,
        plugin_manager: Any | None = None,
        sandbox: Sandbox | None = None,
        *,
        settings: Any | None = None,
    ) -> None:
        self._tools: dict[str, ResearchTool] = {}
        self._plugin_manager = plugin_manager
        self._sandbox = sandbox
        self._settings = settings
        self._register_builtin_tools()
        self._register_evolved_research_tools()

    def _register_builtin_tools(self) -> None:
        async def _web(q: str, **kwargs: Any) -> dict[str, Any]:
            return await web_search_stub(q, int(kwargs.get("num_results", 5)))

        async def _paper(q: str, **kwargs: Any) -> dict[str, Any]:
            return await paper_search_stub(q, str(kwargs.get("source", "arxiv")))

        async def _fetch(u: str, **_kwargs: Any) -> dict[str, Any]:
            return await fetch_url_stub(u)

        async def _exec(cmd: str, **_kwargs: Any) -> dict[str, Any]:
            if not self._sandbox:
                return {"ok": False, "error": "sandbox_not_available"}
            return await sandbox_run_command(self._sandbox, cmd)

        async def _code_audit(claims: list[str], repo_path: str, **_kwargs: Any) -> dict[str, Any]:
            return audit_claims_vs_code(claims, repo_path)

        for t in (
            ResearchTool(
                "research_web_search",
                "Search the public web for current facts (uses project web backend; "
                "falls back to DuckDuckGo when needed).",
                _web,
                parameters=_SCHEMA_WEB,
                required=["query"],
            ),
            ResearchTool(
                "research_paper_search",
                "Search academic paper indexes (arXiv by default; optional Semantic Scholar).",
                _paper,
                parameters=_SCHEMA_PAPER,
                required=["query"],
            ),
            ResearchTool(
                "research_fetch_url",
                "Fetch readable text from a URL (uses project extract tools when configured).",
                _fetch,
                parameters=_SCHEMA_FETCH,
                required=["url"],
            ),
            ResearchTool(
                "research_sandbox_exec",
                "Run a shell command in the research sandbox workspace.",
                _exec,
                requires_sandbox=True,
                parameters=_SCHEMA_SANDBOX,
                required=["command"],
            ),
            ResearchTool(
                "research_code_audit",
                "Audit textual claims against repository code signals.",
                _code_audit,
                parameters=_SCHEMA_AUDIT,
                required=["claims", "repo_path"],
            ),
        ):
            self._tools[t.name] = t

    def _register_evolved_research_tools(self) -> None:
        if self._settings is None:
            return
        try:
            skills_dir = ensure_learning_dirs(self._settings).evolved_skills_dir
        except Exception:
            return
        for p in skills_dir.glob("deepnote-research-*.md"):
            self.register_evolved_tool_note(p)

    def register_evolved_tool_note(self, note_path: Path) -> None:
        """Register a lightweight advisory research tool from an evolved note."""
        try:
            body = note_path.read_text(encoding="utf-8").strip()
        except Exception:
            return
        stem = note_path.stem.replace("deepnote-", "evolved-")
        tool_name = f"research_{stem}".replace("_", "-").replace("-", "_")

        async def _advice(query: str = "", **kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "tool": tool_name,
                "query": query,
                "advice": body[:4000],
                "meta": {"source_note": str(note_path), "extra": kwargs},
            }

        self._tools[tool_name] = ResearchTool(
            tool_name,
            "Evolved research advisory pattern generated from DeepNote/ECAP loop.",
            _advice,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": [],
            },
            required=[],
        )

    def set_sandbox(self, sandbox: Sandbox | None) -> None:
        self._sandbox = sandbox

    def register(self, tool: ResearchTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ResearchTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[ResearchTool]:
        return list(self._tools.values())


async def fire_research_hooks(
    plugin_manager: Any | None,
    event: Any,
    context: dict[str, Any],
) -> None:
    """Best-effort hook fan-out when a running event loop exists."""
    if not plugin_manager:
        return
    he = getattr(plugin_manager, "hook_engine", None)
    if not he:
        return
    try:
        await he.fire(event, context=context)
    except Exception:
        pass
