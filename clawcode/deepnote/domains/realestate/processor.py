from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class RealEstateContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"realestate", "property", "transaction", "contract"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Real Estate Note")
        property_id = re.search(r"\b([A-Z]{2}\d{6,8})\b", raw_content)
        area = re.search(r"(\d+(?:\.\d+)?\s*(?:平方米|平米|m²))", raw_content)
        price = re.search(r"(\d+(?:\.\d+)?\s*(?:万|元|W|w))", raw_content)
        fields: dict[str, Any] = {
            "property_id": property_id.group(1) if property_id else "",
            "area": area.group(1) if area else "",
            "price": price.group(1) if price else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["realestate", "property"] if fields["property_id"] else ["realestate", "contract"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"[A-Z]{2}\d{6,8}|\d+(?:\.\d+)?\s*(?:平方米|平米|m²)|\d+(?:\.\d+)?\s*(?:万|元|W|w)", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "平米" in content and not re.search(r"\d+(?:\.\d+)?\s*(?:平方米|平米|m²)", content):
            errs.append("invalid area format")
        return errs


ProcessorRegistry.register("realestate", RealEstateContentProcessor)

