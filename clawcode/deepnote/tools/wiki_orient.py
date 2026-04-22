from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from ..observer import DeepNoteObserver
from ..wiki_store import WikiStore

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ...llm.tools.base import ToolCall, ToolContext


class WikiOrientTool:
    def info(self):
        from ...llm.tools.base import ToolInfo

        return ToolInfo(
            name="wiki_orient",
            description="Load DeepNote orientation: SCHEMA.md, index.md and recent log.",
            parameters={
                "type": "object",
                "properties": {
                    "log_entries": {"type": "integer", "description": "How many recent log lines to include."},
                },
                "required": [],
            },
            required=[],
        )

    async def run(self, call: ToolCall, context: ToolContext):
        from ...llm.tools.base import ToolResponse
        from ...config import get_settings

        args = call.get_input_dict()
        log_entries = int(args.get("log_entries", 30) or 30)
        obs_input = {"log_entries": log_entries}
        settings = get_settings()
        store = WikiStore.from_settings(settings)
        try:
            logger.info("deepnote_tool_invoke", tool="wiki_orient", log_entries=log_entries)
            DeepNoteObserver.record_pre("wiki_orient", context, obs_input, settings=settings)
            payload = {
                "success": True,
                "orient": store.get_orient_payload(log_entries=max(1, min(log_entries, 120))),
            }
            DeepNoteObserver.record_post("wiki_orient", context, obs_input, {"success": True}, settings=settings)
            return ToolResponse.text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            DeepNoteObserver.record_post("wiki_orient", context, obs_input, {"error": str(exc)}, settings=settings, is_error=True)
            raise
        finally:
            store.close()


def create_wiki_orient_tool(permissions: Any = None) -> WikiOrientTool:
    return WikiOrientTool()

