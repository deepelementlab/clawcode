"""Independent research mode: multi-phase workflows, sub-agents, sandbox hooks."""

from __future__ import annotations

from .settings_models import ResearchConfig

__all__ = ["ResearchConfig"]


def __getattr__(name: str):
    if name == "register_research_cli":
        from .cli import register_research_cli

        return register_research_cli
    raise AttributeError(name)
