"""Load third-party research adapters from ``importlib.metadata`` entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .base import AdapterRegistry, ExternalResearchAdapter

_GROUP = "clawcode.research_adapters"
_registered = False


def iter_entry_point_adapter_classes() -> dict[str, type[ExternalResearchAdapter]]:
    """Return mapping ``entry_point_name -> adapter_class`` for the research group."""
    out: dict[str, type[ExternalResearchAdapter]] = {}
    for ep in entry_points(group=_GROUP):
        try:
            loaded: Any = ep.load()
        except Exception:
            continue
        if not isinstance(loaded, type) or not issubclass(loaded, ExternalResearchAdapter):
            continue
        out[ep.name] = loaded
    return out


def validate_adapter_class(cls: type[Any]) -> None:
    """Ensure ``cls`` subclasses `ExternalResearchAdapter` (for custom loaders)."""
    if not isinstance(cls, type) or not issubclass(cls, ExternalResearchAdapter):
        raise TypeError(f"{cls!r} must be a subclass of ExternalResearchAdapter")


def ensure_entry_point_adapters_registered() -> None:
    """Register all dist entry points into `AdapterRegistry` (idempotent)."""
    global _registered
    if _registered:
        return
    for name, cls in iter_entry_point_adapter_classes().items():
        validate_adapter_class(cls)
        AdapterRegistry.register(name, cls)
    _registered = True
