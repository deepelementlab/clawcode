from __future__ import annotations

from .base import ResearchBackend


class BackendRegistry:
    _items: dict[str, type[ResearchBackend]] = {}

    @classmethod
    def register(cls, name: str, backend_cls: type[ResearchBackend]) -> None:
        cls._items[name] = backend_cls

    @classmethod
    def get(cls, name: str) -> type[ResearchBackend] | None:
        return cls._items.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._items.keys())
