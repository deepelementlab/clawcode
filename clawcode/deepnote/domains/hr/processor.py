from __future__ import annotations

import re
from typing import Any

from ...processors.base import DomainContentProcessor
from ...processors.registry import ProcessorRegistry


class HRContentProcessor(DomainContentProcessor):
    def can_process(self, content_type: str, source_format: str) -> bool:
        _ = source_format
        return content_type.lower() in {"hr", "employee", "jobposting", "performancereview"}

    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        title = str(source_meta.get("title") or "HR Note")
        employee_id = re.search(r"\b((?:EMP|HR)\d{4,6})\b", raw_content)
        department = re.search(r"(技术部|销售部|人事部|财务部|运营部)", raw_content)
        salary = re.search(r"(\d{2,3}K-\d{2,3}K)", raw_content)
        fields: dict[str, Any] = {
            "employee_id": employee_id.group(1) if employee_id else "",
            "department": department.group(1) if department else "",
            "salary_range": salary.group(1) if salary else "",
        }
        return {
            "title": title,
            "section": str(source_meta.get("section") or "entities"),
            "body": raw_content,
            "tags": ["hr", "employee"] if fields["employee_id"] else ["hr", "recruitment"],
            "fields": fields,
            "entities": [],
            "relations": [],
        }

    def enhance_search(self, page_content: str) -> dict[str, Any]:
        terms = re.findall(r"(?:EMP|HR)\d{4,6}|\d{2,3}K-\d{2,3}K|技术部|销售部|人事部|财务部|运营部", page_content)
        return {"searchable_text": page_content, "boost_terms": terms[:20], "semantic_vectors": []}

    def validate_content(self, content: str) -> list[str]:
        errs: list[str] = []
        if "K-" in content and not re.search(r"\d{2,3}K-\d{2,3}K", content):
            errs.append("invalid salary range format")
        return errs


ProcessorRegistry.register("hr", HRContentProcessor)

