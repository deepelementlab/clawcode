from __future__ import annotations

from typing import Any


class LoopDetectionMiddleware:
    """Detect repeated assistant outputs and flag possible stalls."""

    name = "loop_detection"

    def __init__(self, repeat_threshold: int = 3) -> None:
        self._repeat_threshold = max(2, repeat_threshold)

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        last = ctx.get("last_assistant_text") or ""
        history: list[str] = list(ctx.get("assistant_tail") or [])
        if last:
            history = (history + [last])[-10:]
        repeats = sum(1 for h in history if h == last) if last else 0
        flags = list(ctx.get("flags") or [])
        if repeats >= self._repeat_threshold:
            flags.append("possible_loop")
        return {**ctx, "assistant_tail": history, "flags": flags}
