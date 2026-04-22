from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from ..observer import DeepNoteObserver
from ..wiki_store import WikiStore

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ...llm.tools.base import ToolCall, ToolContext


class WikiIngestTool:
    _ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2})\b")

    def _extract_entity_candidates(self, title: str, source: str, summary: str) -> list[str]:
        text = "\n".join([title, summary, source[:3000]])
        candidates: list[str] = []
        for item in self._ENTITY_RE.findall(text):
            cleaned = " ".join(item.split()).strip()
            if len(cleaned) < 3:
                continue
            if cleaned.lower() in {"the", "this", "that", "with", "from"}:
                continue
            candidates.append(cleaned)
        # Keep stable order and cap fanout.
        seen: set[str] = set()
        out: list[str] = []
        for c in candidates:
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
            if len(out) >= 8:
                break
        return out

    def info(self):
        from ...llm.tools.base import ToolInfo

        return ToolInfo(
            name="wiki_ingest",
            description=(
                "Ingest URL/file/text into DeepNote wiki. Saves immutable raw source, "
                "creates or updates wiki pages, refreshes index and link graph."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source content or URL or filepath text."},
                    "source_type": {"type": "string", "enum": ["url", "file", "text"], "description": "Source type hint."},
                    "title": {"type": "string", "description": "Source title / page title."},
                    "section": {"type": "string", "enum": ["entities", "concepts", "comparisons", "queries"], "description": "Target wiki section."},
                    "summary": {"type": "string", "description": "Compiled wiki page content."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "extract_entities": {"type": "boolean"},
                    "max_entities": {"type": "integer", "description": "Maximum auto entity pages to create."},
                },
                "required": ["source", "title"],
            },
            required=["source", "title"],
        )

    async def run(self, call: ToolCall, context: ToolContext):
        from ...llm.tools.base import ToolResponse
        from ...config import get_settings

        args = call.get_input_dict()
        source = str(args.get("source", "")).strip()
        title = str(args.get("title", "")).strip()
        if not source or not title:
            return ToolResponse.error(json.dumps({"success": False, "error": "source and title are required"}, ensure_ascii=False))
        source_type = str(args.get("source_type", "text") or "text").strip().lower()
        section = str(args.get("section", "concepts") or "concepts").strip().lower()
        if section not in {"entities", "concepts", "comparisons", "queries"}:
            section = "concepts"
        summary = str(args.get("summary", "") or "").strip()
        tags = args.get("tags") if isinstance(args.get("tags"), list) else ["concept"]
        extract_entities = bool(args.get("extract_entities", True))
        max_entities = int(args.get("max_entities", 4) or 4)
        max_entities = max(0, min(max_entities, 12))
        obs_input = {
            "title": title,
            "source_type": source_type,
            "section": section,
            "extract_entities": extract_entities,
            "max_entities": max_entities,
        }

        settings = get_settings()
        store = WikiStore.from_settings(settings)
        try:
            logger.info("deepnote_tool_invoke", tool="wiki_ingest", title=title, section=section)
            DeepNoteObserver.record_pre("wiki_ingest", context, obs_input, settings=settings)
            raw_path = store.save_raw_source(
                "articles" if source_type in {"url", "text"} else "papers",
                title=title,
                content=source,
            )
            page = store.write_page(
                section=section,
                title=title,
                body=summary or f"## Summary\n\n{source[:1200]}",
                tags=[str(t) for t in tags if str(t).strip()],
                sources=[str(raw_path.relative_to(store.root))],
            )

            created_entities: list[str] = []
            if extract_entities and bool(store.config.ingest.extract_entities):
                entity_candidates = self._extract_entity_candidates(title=title, source=source, summary=summary)
                for entity in entity_candidates[:max_entities]:
                    slug = store.slugify(entity)
                    entity_path = store.root / "entities" / f"{slug}.md"
                    if entity_path.exists():
                        continue
                    entity_body = (
                        f"## Overview\n\n{entity} is mentioned in [[{store.slugify(title)}]].\n\n"
                        f"## Context\n\nDerived from source: [[{store.slugify(title)}]]."
                    )
                    store.write_page(
                        section="entities",
                        title=entity,
                        body=entity_body,
                        tags=["entity"],
                        sources=[str(raw_path.relative_to(store.root))],
                    )
                    created_entities.append(entity)

            payload = {
                "success": True,
                "raw_source": str(raw_path),
                "page": str(page),
                "section": section,
                "created_entities": created_entities,
            }
            DeepNoteObserver.record_post(
                "wiki_ingest",
                context,
                obs_input,
                {"page": str(page), "created_entities": len(created_entities)},
                settings=settings,
                reasoning_effort="high" if created_entities else "medium",
            )
            return ToolResponse.text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            DeepNoteObserver.record_post("wiki_ingest", context, obs_input, {"error": str(exc)}, settings=settings, is_error=True)
            raise
        finally:
            store.close()


def create_wiki_ingest_tool(permissions: Any = None) -> WikiIngestTool:
    return WikiIngestTool()

