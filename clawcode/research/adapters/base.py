"""Pluggable backends for research runs (e.g. external CLI runtimes)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ..types import ResearchEvent


class ExternalResearchAdapter(ABC):
    """Contract for delegating research to an out-of-process or alternate runtime."""

    @abstractmethod
    async def initialize(self, config: dict[str, Any]) -> None:
        """Prepare credentials, paths, and subprocess environment."""

    @abstractmethod
    async def execute_research(
        self,
        topic: str,
        workflow: str,
        context: dict[str, Any],
    ) -> AsyncIterator["ResearchEvent"]:
        """Stream research progress and artifacts."""

    @abstractmethod
    async def list_capabilities(self) -> list[str]:
        """Return workflow ids or feature flags supported by this adapter."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources."""


class AdapterRegistry:
    """Register named adapter implementations without hard imports."""

    _adapters: dict[str, type[ExternalResearchAdapter]] = {}

    @classmethod
    def register(cls, name: str, adapter_class: type[ExternalResearchAdapter]) -> None:
        cls._adapters[name] = adapter_class

    @classmethod
    def get(cls, name: str) -> type[ExternalResearchAdapter] | None:
        return cls._adapters.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._adapters.keys())
