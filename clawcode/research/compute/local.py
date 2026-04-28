from __future__ import annotations

from typing import Any

from .base import ComputeBackend


class LocalComputeBackend(ComputeBackend):
    async def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "backend": "local", "spec": spec}
