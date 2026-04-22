from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..domain_schema import DomainSchema


class DomainContentProcessor(ABC):
    def __init__(self, schema: DomainSchema) -> None:
        self.schema = schema

    @abstractmethod
    def can_process(self, content_type: str, source_format: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def process_ingest(self, raw_content: str, source_meta: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def enhance_search(self, page_content: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_content(self, content: str) -> list[str]:
        raise NotImplementedError

    def get_entity_type(self, entity_name: str) -> str | None:
        name = (entity_name or "").lower()
        for entity_def in self.schema.entities:
            if entity_def.name.lower() in name:
                return entity_def.name
        return None

