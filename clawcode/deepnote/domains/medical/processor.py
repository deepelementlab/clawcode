from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class MedicalContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"disease", "medication", "symptom", "medical"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "Medical Note")
        icd10_match = re.search(r"ICD-10:\s*([A-Z][0-9]{2}\.[0-9])", raw_content)
        symptoms = re.findall(r"[Ss]ymptoms?:\s*([^\n]+)", raw_content)
        fields: dict[str, Any] = {
            "icd10_code": icd10_match.group(1) if icd10_match else "",
            "symptoms": [s.strip() for s in symptoms if s.strip()],
        }
        tags = ["medical", "disease"] if fields["icd10_code"] else ["medical", "note"]
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": tags,
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "ICD-10:" in content and not re.search(r"ICD-10:\s*[A-Z][0-9]{2}\.[0-9]", content):
            errs.append("invalid ICD-10 code format")
        return errs


ProcessorRegistry.register("medical", MedicalContentProcessor)

