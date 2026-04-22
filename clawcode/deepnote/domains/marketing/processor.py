from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class MarketingContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"marketing", "campaign", "customer", "channel"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Marketing Note")
        budget = re.search(r"(\d+(?:\.\d+)?\s*(?:万|元|W|w|USD|CNY)?)", raw_content)
        conversion = re.search(r"(\d+\.?\d*\s*%)", raw_content)
        roi = re.search(r"(ROI\s*[:=]?\s*\d+\.?\d*(?::\d*\.?\d*)?)", raw_content)
        fields: dict[str, Any] = {
            "budget": budget.group(1) if budget else "",
            "conversion_rate": conversion.group(1) if conversion else "",
            "roi": roi.group(1) if roi else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["marketing", "campaign"] if fields["conversion_rate"] else ["marketing", "channel"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"\d+\.?\d*\s*(?:万|元|W|w|USD|CNY)?|\d+\.?\d*\s*%|ROI\s*[:=]?\s*\d+\.?\d*(?::\d*\.?\d*)?", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "ROI" in content and not re.search(r"ROI\s*[:=]?\s*\d+\.?\d*(?::\d*\.?\d*)?", content):
            errs.append("invalid ROI format")
        return errs


ProcessorRegistry.register("marketing", MarketingContentProcessor)

