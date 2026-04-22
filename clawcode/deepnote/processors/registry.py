from __future__ import annotations

from .base import DomainContentProcessor


class ProcessorRegistry:
    _processors: dict[str, type[DomainContentProcessor]] = {}

    @classmethod
    def register(cls, domain_id: str, processor_class: type[DomainContentProcessor]) -> None:
        cls._processors[domain_id] = processor_class

    @classmethod
    def get_processor(cls, domain_id: str, schema: object) -> DomainContentProcessor | None:
        processor_class = cls._processors.get(domain_id)
        if processor_class is None:
            return None
        return processor_class(schema)  # type: ignore[arg-type]

    @classmethod
    def list_processors(cls) -> list[str]:
        return sorted(cls._processors.keys())

