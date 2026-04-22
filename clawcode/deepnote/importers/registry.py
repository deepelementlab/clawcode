from __future__ import annotations

from pathlib import Path

from .base import DomainKnowledgeImporter


class ImporterRegistry:
    _importers: dict[str, type[DomainKnowledgeImporter]] = {}

    @classmethod
    def register(cls, fmt: str, importer_class: type[DomainKnowledgeImporter]) -> None:
        cls._importers[fmt.lower().strip()] = importer_class

    @classmethod
    def resolve(cls, source: Path | str, fmt: str = "auto") -> DomainKnowledgeImporter | None:
        chosen = fmt.lower().strip()
        if chosen == "auto":
            suffix = Path(source).suffix.lower().lstrip(".") if str(source) else ""
            chosen = suffix or "text"
        klass = cls._importers.get(chosen)
        if klass is None:
            return None
        return klass()

    @classmethod
    def list_formats(cls) -> list[str]:
        return sorted(cls._importers.keys())

