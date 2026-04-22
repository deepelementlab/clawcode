from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from ..observer import DeepNoteObserver
from ..wiki_store import WikiStore

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ...llm.tools.base import ToolCall, ToolContext


class WikiHistoryTool:
    def info(self):
        from ...llm.tools.base import ToolInfo

        return ToolInfo(
            name="wiki_history",
            description="Inspect DeepNote page history commits.",
            parameters={
                "type": "object",
                "properties": {
                    "page": {"type": "string", "description": "Optional page path for filtering history."},
                    "limit": {"type": "integer", "description": "Maximum number of history rows."},
                },
                "required": [],
            },
            required=[],
        )

    async def run(self, call: ToolCall, context: ToolContext):
        from ...llm.tools.base import ToolResponse
        from ...config import get_settings

        args = call.get_input_dict()
        page = str(args.get("page", "") or "").strip() or None
        limit = int(args.get("limit", 30) or 30)
        limit = max(1, min(limit, 200))
        obs_input = {"page": page, "limit": limit}

        settings = get_settings()
        store = WikiStore.from_settings(settings)
        try:
            logger.info("deepnote_tool_invoke", tool="wiki_history", page=page, limit=limit)
            DeepNoteObserver.record_pre("wiki_history", context, obs_input, settings=settings)
            rows = store.history.list_commits(page_path=page, limit=limit)
            DeepNoteObserver.record_post("wiki_history", context, obs_input, {"row_count": len(rows)}, settings=settings)
            return ToolResponse.text(json.dumps({"success": True, "rows": rows}, ensure_ascii=False))
        except Exception as exc:
            DeepNoteObserver.record_post("wiki_history", context, obs_input, {"error": str(exc)}, settings=settings, is_error=True)
            raise
        finally:
            store.close()


def create_wiki_history_tool(permissions: Any = None) -> WikiHistoryTool:
    return WikiHistoryTool()

