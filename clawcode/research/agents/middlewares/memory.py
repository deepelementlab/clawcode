from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...memory.storage import ResearchMemoryStorage


class MemoryMiddleware:
    """Inject recent memory snippets before model calls."""

    name = "memory"

    def __init__(self, storage: "ResearchMemoryStorage | None") -> None:
        self._storage = storage

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if not self._storage:
            return ctx
        topic = str(ctx.get("topic") or "")
        snippets = await self._storage.recall(topic, limit=5)
        if not snippets:
            return ctx
        block = "\n".join(f"- {s}" for s in snippets)
        extras = str(ctx.get("memory_block") or "")
        merged = (extras + "\n" + block).strip() if extras else block
        return {**ctx, "memory_block": merged}
