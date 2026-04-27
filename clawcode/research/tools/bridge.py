"""Bridge `ResearchTool` callables to `llm.tools.base.BaseTool` for the Agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ...llm.tools.base import BaseTool, ToolCall, ToolContext, ToolInfo, ToolResponse
from .registry import ResearchTool, ToolRegistry

logger = logging.getLogger(__name__)


class ResearchToolAdapter(BaseTool):
    """Wraps a research-mode tool so the standard Agent can invoke it."""

    def __init__(self, rt: ResearchTool) -> None:
        self._rt = rt

    def info(self) -> ToolInfo:
        return ToolInfo(
            name=self._rt.name,
            description=self._rt.description,
            parameters=self._rt.parameters,
            required=self._rt.required,
        )

    @property
    def requires_permission(self) -> bool:
        if self._rt.name == "research_sandbox_exec":
            return True
        return False

    @property
    def is_dangerous(self) -> bool:
        return self._rt.name == "research_sandbox_exec"

    async def run(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        inp = call.get_input_dict()
        try:
            payload = await self._invoke(inp)
            text = json.dumps(payload, ensure_ascii=False)
            is_err = bool(payload.get("error")) or (
                isinstance(payload.get("ok"), bool) and payload.get("ok") is False
            )
            return ToolResponse(content=text, is_error=is_err)
        except Exception as e:  # noqa: BLE001
            logger.exception("research tool %s failed", self._rt.name)
            return ToolResponse.error(str(e))

    async def _invoke(self, inp: dict[str, Any]) -> dict[str, Any]:
        name = self._rt.name
        h = self._rt.handler

        if name == "research_web_search":
            raw = h(
                str(inp.get("query", "")),
                num_results=int(inp.get("num_results", 5)),
            )
        elif name == "research_paper_search":
            raw = h(
                str(inp.get("query", "")),
                source=str(inp.get("source", "arxiv")),
            )
        elif name == "research_fetch_url":
            raw = h(str(inp.get("url", "")))
        elif name == "research_sandbox_exec":
            raw = h(str(inp.get("command", "")))
        else:
            raw = h(**inp)

        if asyncio.iscoroutine(raw):
            out = await raw
        else:
            out = raw
        return out if isinstance(out, dict) else {"result": out}


def research_tools_as_base_tools(registry: ToolRegistry) -> list[BaseTool]:
    """Build `BaseTool` list from a research `ToolRegistry`."""
    return [ResearchToolAdapter(t) for t in registry.list_all()]
