from __future__ import annotations

from typing import Any


class TitleMiddleware:
    """Derive a short session title from the user topic."""

    name = "title"

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("title"):
            return ctx
        topic = (ctx.get("topic") or "").strip()
        title = topic[:80] + ("…" if len(topic) > 80 else "") if topic else "Research"
        return {**ctx, "title": title}
