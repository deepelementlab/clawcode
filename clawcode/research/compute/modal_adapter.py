from __future__ import annotations

from typing import Any

from .base import ComputeBackend


class ModalComputeAdapter(ComputeBackend):
    async def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": "modal",
            "error": "modal adapter is reserved for future integration",
            "spec": spec,
        }
