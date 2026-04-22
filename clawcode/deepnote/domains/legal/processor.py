from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class LegalContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"legal", "lawarticle", "case", "contract"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Legal Note")
        article = re.search(r"(第\d+条)", raw_content)
        law_name = re.search(r"(《[^》]+》)", raw_content)
        case_number = re.search(r"(\(\d{4}\).*?第\d+号)", raw_content)
        court = re.search(r"(?:法院|法庭)[:：]\s*([^\n]+)", raw_content)
        fields: dict[str, Any] = {
            "article_number": article.group(1) if article else "",
            "law_name": law_name.group(1) if law_name else "",
            "case_number": case_number.group(1) if case_number else "",
            "court": court.group(1).strip() if court else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["legal", "law"] if fields["article_number"] else ["legal", "case"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        law_refs = re.findall(r"第\d+条|《[^》]+》|\(\d{4}\).*?第\d+号", page_content)
        return {"searchable_text": page_content, "boost_terms": law_refs[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "第" in content and "条" in content and not re.search(r"第\d+条", content):
            errs.append("invalid article number format")
        return errs


ProcessorRegistry.register("legal", LegalContentProcessor)

