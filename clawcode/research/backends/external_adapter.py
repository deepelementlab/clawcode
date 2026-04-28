from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..types import ResearchEvent
from .base import ResearchBackend


class ExternalAdapterBackend(ResearchBackend):
    """Placeholder backend for future external runtime integration."""

    async def execute_workflow(self, workflow: str, topic: str, context: dict[str, Any]) -> AsyncIterator[ResearchEvent]:
        yield ResearchEvent(
            "warning",
            {"message": "external adapter backend is reserved and not configured"},
        )

    async def spawn_agent(self, agent_type: str, task: str) -> str:
        return f"external:{agent_type}:{task[:24]}"
