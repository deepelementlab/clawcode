from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..engine.orchestrator import ResearchOrchestrator
from ..types import ResearchEvent, ResearchTask
from .base import ResearchBackend


class NativeResearchBackend(ResearchBackend):
    def __init__(self, orchestrator: ResearchOrchestrator, task_factory: Any) -> None:
        self._orch = orchestrator
        self._task_factory = task_factory

    async def execute_workflow(self, workflow: str, topic: str, context: dict[str, Any]) -> AsyncIterator[ResearchEvent]:
        task: ResearchTask = self._task_factory(topic=topic, workflow_type=workflow, context=context)
        async for ev in self._orch.run(task):
            yield ev

    async def spawn_agent(self, agent_type: str, task: str) -> str:
        return f"native:{agent_type}:{task[:32]}"
