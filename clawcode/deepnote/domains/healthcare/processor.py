from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class HealthcareContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"healthcare", "healthrecord", "vitalsign", "medication"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Healthcare Note")
        blood_pressure = re.search(r"(\d{2,3}/\d{2,3}\s*(?:mmHg)?)", raw_content)
        glucose = re.search(r"(\d+\.?\d*\s*(?:mmol/L|mg/dL))", raw_content)
        dosage = re.search(r"(\d+\.?\d*\s*(?:mg|g|ml|片|粒|支))", raw_content)
        fields: dict[str, Any] = {
            "blood_pressure": blood_pressure.group(1) if blood_pressure else "",
            "blood_glucose": glucose.group(1) if glucose else "",
            "dosage": dosage.group(1) if dosage else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["healthcare", "vital"] if fields["blood_pressure"] else ["healthcare", "medication"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"\d{2,3}/\d{2,3}\s*(?:mmHg)?|\d+\.?\d*\s*(?:mmol/L|mg/dL)|\d+\.?\d*\s*(?:mg|g|ml|片|粒|支)", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "/" in content and "mmHg" in content and not re.search(r"\d{2,3}/\d{2,3}\s*(?:mmHg)?", content):
            errs.append("invalid blood pressure format")
        return errs


ProcessorRegistry.register("healthcare", HealthcareContentProcessor)

