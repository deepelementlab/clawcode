from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class ResearchContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"research", "paper", "experiment", "dataset"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Research Note")
        doi = re.search(r"(10\.\d{4,5}/[^\s]+)", raw_content)
        year = re.search(r"\b((?:19|20)\d{2})\b", raw_content)
        impact = re.search(r"(IF\s*[:=]?\s*\d+\.?\d*)", raw_content)
        fields: dict[str, Any] = {
            "doi": doi.group(1) if doi else "",
            "year": year.group(1) if year else "",
            "impact_factor": impact.group(1) if impact else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["research", "paper"] if fields["doi"] else ["research", "experiment"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"10\.\d{4,5}/[^\s]+|(?:19|20)\d{2}|IF\s*[:=]?\s*\d+\.?\d*", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "10." in content and not re.search(r"10\.\d{4,5}/[^\s]+", content):
            errs.append("invalid DOI format")
        return errs


ProcessorRegistry.register("research", ResearchContentProcessor)

