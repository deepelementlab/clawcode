from __future__ import annotations

from typing import Any


class TokenUsageMiddleware:
    name = "token_usage"

    async def process(self, ctx: dict[str, Any]) -> dict[str, Any]:
        usage = ctx.get("token_usage")
        if usage is None:
            usage = {"input": 0, "output": 0, "total": 0}
            ctx = {**ctx, "token_usage": usage}
        return ctx
