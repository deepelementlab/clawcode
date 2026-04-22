from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class FinanceContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"finance", "financialproduct", "transaction", "riskindicator"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Finance Note")
        product_code = re.search(r"\b([A-Z]{2,6}\d{3,6})\b", raw_content)
        amount = re.search(r"[¥$€]\s*(\d+(?:,\d{3})*(?:\.\d{2})?)", raw_content)
        yield_rate = re.search(r"(\d+(?:\.\d+)?)\s*%", raw_content)
        fields: dict[str, Any] = {
            "product_code": product_code.group(1) if product_code else "",
            "amount": amount.group(1).replace(",", "") if amount else "",
            "yield_rate": f"{yield_rate.group(1)}%" if yield_rate else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["finance", "risk"] if fields["yield_rate"] else ["finance", "transaction"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"[A-Z]{2,6}\d{3,6}|[¥$€]\s*\d+(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d+)?%", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "%" in content and not re.search(r"\d+(?:\.\d+)?\s*%", content):
            errs.append("invalid yield rate format")
        return errs


ProcessorRegistry.register("finance", FinanceContentProcessor)

