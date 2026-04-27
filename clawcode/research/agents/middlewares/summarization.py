from __future__ import annotations

from typing import Any


class SummarizationMiddleware:
    """Trim overly long message stacks to keep prompts bounded."""

    name = "summarization"

    def __init__(self, max_messages: int = 40) -> None:
        self._max_messages = max(8, max_messages)

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        msgs = list(ctx.get("messages") or [])
        if len(msgs) <= self._max_messages:
            return ctx
        trimmed = msgs[-self._max_messages :]
        note = (
            f"[context trimmed: kept last {self._max_messages} messages "
            f"of {len(msgs)}]"
        )
        return {**ctx, "messages": trimmed, "trim_note": note}
