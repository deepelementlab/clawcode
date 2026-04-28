from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from ..types import ResearchEvent


class ResearchBackend(ABC):
    @abstractmethod
    async def execute_workflow(self, workflow: str, topic: str, context: dict[str, Any]) -> AsyncIterator[ResearchEvent]:
        raise NotImplementedError

    @abstractmethod
    async def spawn_agent(self, agent_type: str, task: str) -> str:
        raise NotImplementedError
