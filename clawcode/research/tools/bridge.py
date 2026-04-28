"""Bridge `ResearchTool` callables to `llm.tools.base.BaseTool` for the Agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ...deepnote.observer import DeepNoteObserver
from ...llm.tools.base import BaseTool, ToolCall, ToolContext, ToolInfo, ToolResponse
from .registry import ResearchTool, ToolRegistry

logger = logging.getLogger(__name__)


class ResearchToolAdapter(BaseTool):
    """Wraps a research-mode tool so the standard Agent can invoke it."""

    def __init__(self, rt: ResearchTool, *, settings: Any | None = None) -> None:
        self._rt = rt
        self._settings = settings

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
            DeepNoteObserver.record_pre(
                self._rt.name,
                context,
                inp,
                settings=self._settings,
            )
            payload = await self._invoke(inp)
            DeepNoteObserver.record_post(
                self._rt.name,
                context,
                inp,
                payload,
                settings=self._settings,
                is_error=bool(payload.get("error")) or (
                    isinstance(payload.get("ok"), bool) and payload.get("ok") is False
                ),
            )
            text = json.dumps(payload, ensure_ascii=False)
            is_err = bool(payload.get("error")) or (
                isinstance(payload.get("ok"), bool) and payload.get("ok") is False
            )
            return ToolResponse(content=text, is_error=is_err)
        except Exception as e:  # noqa: BLE001
            logger.exception("research tool %s failed", self._rt.name)
            DeepNoteObserver.record_post(
                self._rt.name,
                context,
                inp,
                {"error": str(e)},
                settings=self._settings,
                is_error=True,
            )
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


def research_tools_as_base_tools(
    registry: ToolRegistry,
    *,
    settings: Any | None = None,
) -> list[BaseTool]:
    """Build `BaseTool` list from a research `ToolRegistry`."""
    return [ResearchToolAdapter(t, settings=settings) for t in registry.list_all()]
