from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ComputeBackend(ABC):
    @abstractmethod
    async def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
