"""Middleware protocol for research LLM turns."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResearchMiddleware(Protocol):
    """Async hook around a research context dict."""

    name: str

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Mutate or enrich ctx (messages, usage, todos, ...)."""


class MiddlewareChain:
    """Ordered async pipeline."""

    def __init__(self, middlewares: list[ResearchMiddleware]) -> None:
        self._middlewares = list(middlewares)

    async def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        out = dict(ctx)
        for m in self._middlewares:
            out = await m.process(out)
        return out
