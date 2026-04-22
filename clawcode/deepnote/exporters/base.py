from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..wiki_store import WikiStore


class DomainKnowledgeExporter(ABC):
    supported_formats: list[str] = []

    @abstractmethod
    async def export_to_file(
        self, store: WikiStore, output_path: Path, options: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_export_preview(self, store: WikiStore, options: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

