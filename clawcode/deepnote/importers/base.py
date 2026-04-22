from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator


class DomainKnowledgeImporter(ABC):
    supported_formats: list[str] = []

    @abstractmethod
    async def import_from_file(
        self, file_path: Path, options: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def import_from_url(self, url: str, options: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def validate_source(self, source: Path | str) -> tuple[bool, str]:
        raise NotImplementedError

