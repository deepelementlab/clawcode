from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class TechContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"tech", "apiendpoint", "designpattern", "techstack"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Tech Note")
        endpoint = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s]+)", raw_content)
        version = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", raw_content)
        language = re.search(r"(Python|Java|JavaScript|TypeScript|Go|Rust|C#|C\+\+)", raw_content, flags=re.I)
        fields: dict[str, Any] = {
            "method": endpoint.group(1) if endpoint else "",
            "path": endpoint.group(2) if endpoint else "",
            "version": version.group(1) if version else "",
            "language": language.group(1) if language else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["tech", "api"] if fields["path"] else ["tech", "notes"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"\b(?:GET|POST|PUT|DELETE|PATCH)\b|/[A-Za-z0-9/_-]+|v?\d+\.\d+(?:\.\d+)?", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "GET " in content and not re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\s+/[^\s]+", content):
            errs.append("invalid API endpoint format")
        return errs


ProcessorRegistry.register("tech", TechContentProcessor)

