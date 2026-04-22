from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class EducationContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"education", "course", "knowledgepoint", "learningpath"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Education Note")
        course_code = re.search(r"\b([A-Z]{2,4}\d{3,4})\b", raw_content)
        credits = re.search(r"(\d+(?:\.\d)?)\s*学分", raw_content)
        level = re.search(r"(初级|中级|高级|L\d)", raw_content)
        fields: dict[str, Any] = {
            "course_code": course_code.group(1) if course_code else "",
            "credits": credits.group(1) if credits else "",
            "level": level.group(1) if level else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["education", "course"] if fields["course_code"] else ["education", "knowledge"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"[A-Z]{2,4}\d{3,4}|初级|中级|高级|L\d", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "学分" in content and not re.search(r"\d+(?:\.\d)?\s*学分", content):
            errs.append("invalid credits format")
        return errs


ProcessorRegistry.register("education", EducationContentProcessor)

