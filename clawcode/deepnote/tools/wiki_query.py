from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from ..observer import DeepNoteObserver
from ..wiki_store import WikiStore

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ...llm.tools.base import ToolCall, ToolContext


class WikiQueryTool:
    def info(self):
        from ...llm.tools.base import ToolInfo

        return ToolInfo(
            name="wiki_query",
            description="Query DeepNote wiki using keyword, semantic, or hybrid retrieval.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language or keyword query."},
                    "mode": {"type": "string", "enum": ["keyword", "semantic", "hybrid"]},
                    "limit": {"type": "integer", "description": "Maximum result count (default 10)."},
                },
                "required": ["query"],
            },
            required=["query"],
        )

    async def run(self, call: ToolCall, context: ToolContext):
        from ...llm.tools.base import ToolResponse
        from ...config import get_settings

        args = call.get_input_dict()
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResponse.error(json.dumps({"success": False, "error": "query is required"}, ensure_ascii=False))
        mode = str(args.get("mode", "hybrid") or "hybrid").strip().lower()
        limit = int(args.get("limit", 10) or 10)
        limit = max(1, min(limit, 200))
        obs_input = {"query": query, "mode": mode, "limit": limit}

        settings = get_settings()
        store = WikiStore.from_settings(settings)
        try:
            logger.info("deepnote_tool_invoke", tool="wiki_query", mode=mode, limit=limit)
            DeepNoteObserver.record_pre("wiki_query", context, obs_input, settings=settings)
            results = store.query(query=query, mode=mode, limit=limit)
            payload = {"success": True, "query": query, "mode": mode, "results": results}
            DeepNoteObserver.record_post("wiki_query", context, obs_input, {"result_count": len(results)}, settings=settings)
            return ToolResponse.text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            DeepNoteObserver.record_post("wiki_query", context, obs_input, {"error": str(exc)}, settings=settings, is_error=True)
            raise
        finally:
            store.close()


def create_wiki_query_tool(permissions: Any = None) -> WikiQueryTool:
    return WikiQueryTool()

