"""Optional post-turn memory persistence."""

from __future__ import annotations

from typing import Any

from .queue import MemoryWriteQueue
from .updater import MemoryFactUpdater


class ResearchMemoryPipelineMiddleware:
    """After a phase completes, enqueue facts from the latest assistant text."""

    name = "memory_pipeline"

    def __init__(self, queue: MemoryWriteQueue | None) -> None:
        self._queue = queue
        self._updater = MemoryFactUpdater()

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not self._queue:
            return ctx
        topic = str(ctx.get("topic") or "")
        text = str(ctx.get("last_assistant_text") or "")
        if topic and text:
            await self._updater.persist(self._queue, topic, text)
        return ctx
