from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class ManufacturingContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"manufacturing", "process", "qualitycheck", "equipment"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Manufacturing Note")
        process_id = re.search(r"\b(PRO-[A-Z]{2,4}-\d{4})\b", raw_content)
        equipment_id = re.search(r"\b(EQ-[A-Z]{2,4}-\d{4,6})\b", raw_content)
        tolerance = re.search(r"(±\d+\.?\d*\s*(?:mm|cm|m|kg|g))", raw_content)
        fields: dict[str, Any] = {
            "process_id": process_id.group(1) if process_id else "",
            "equipment_id": equipment_id.group(1) if equipment_id else "",
            "tolerance": tolerance.group(1) if tolerance else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["manufacturing", "process"] if fields["process_id"] else ["manufacturing", "equipment"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"PRO-[A-Z]{2,4}-\d{4}|EQ-[A-Z]{2,4}-\d{4,6}|±\d+\.?\d*\s*(?:mm|cm|m|kg|g)", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "±" in content and not re.search(r"±\d+\.?\d*\s*(?:mm|cm|m|kg|g)", content):
            errs.append("invalid tolerance format")
        return errs


ProcessorRegistry.register("manufacturing", ManufacturingContentProcessor)

