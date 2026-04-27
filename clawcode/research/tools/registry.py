"""Research-scoped tool registry with optional plugin hook fan-out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..sandbox.base import Sandbox
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


@dataclass
class ResearchTool:
    name: str
    description: str
    handler: Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]
    requires_sandbox: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(self, plugin_manager: Any | None = None, sandbox: Sandbox | None = None) -> None:
        self._tools: dict[str, ResearchTool] = {}
        self._plugin_manager = plugin_manager
        self._sandbox = sandbox
        self._register_builtin_tools()

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
        ):
            self._tools[t.name] = t

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
